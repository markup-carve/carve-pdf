"""Pygments lexer for the Carve markup language.

Vendored from markup-carve/pygments-carve main (MIT) for offline PDF rendering.

Carve is a lightweight markup language for documents and the web. Its inline
delimiters
deliberately differ from Markdown's, which is why a Markdown lexer produces
actively wrong output on a Carve document rather than merely plain text:

===================  ==================  ==========================
Carve                means               Markdown would read it as
===================  ==================  ==========================
``*bold*``           strong              emphasis
``/italic/``         emphasis            literal slashes
``_under_``          underline           emphasis
``~strike~``         strikethrough       subscript (Djot) / literal
``{=mark=}``         highlight           literal braces
``{^sup^}``          superscript         literal braces
===================  ==================  ==========================

WHY THE BLOCK OPENERS ARE NOT ANCHORED AT COLUMN 0. Carve opens a block at
column 0, or at an enclosing container's content column - nowhere in between.
So ``  # H`` at document level is a paragraph, while the same opener at a list
item's content column is a real heading. Telling those apart needs a container
model that tracks the item's content column. Pygments' state stack could carry
one, but the sibling grammars in carve-grammars (Prism, highlight.js) do not,
and this lexer keeps their trade-off on purpose so the three agree: block
openers match at any indent and knowingly over-colour the rare
indented-at-document-level case, rather than under-colouring the common valid
shape of an indented construct inside a list item. The TextMate grammar in
carve-grammars is the surface that makes the distinction, and the divergence is
documented there under "Where the three grammars deliberately differ".

WHY AN ATTRIBUTE BLOCK IS ONE TOKEN. ``{#id .cls key="v" :lang}`` is emitted
whole as ``Name.Attribute`` rather than split into id, class, key, value and
language parts. Splitting reads better in isolation, but an attribute block can
carry a brace inside a quoted value, a language tag, and a bare key that is not
an attribute at all, and the sibling grammars treat the block as one unit; a
consumer asking "is this text inside an attribute block" must get the same
answer here as it does there.

Spec: https://markup-carve.github.io/carve/
"""

import bisect
import re
import unicodedata

from pygments.lexer import (
    RegexLexer,
    RegexLexerMeta,
    bygroups,
    do_insertions,
    include,
    using,
    this,
)
from pygments.lexers import get_lexer_by_name
from pygments.token import (
    Comment,
    Generic,
    Keyword,
    Literal,
    Name,
    Number,
    Operator,
    Punctuation,
    String,
    Text,
)
from pygments.util import ClassNotFound, get_bool_opt

__all__ = ['CarveLexer']

#: A leading margin. A byte order mark at the start of a document is not
#: content, so a block opener behind one is still a block opener. Anywhere else
#: it is content, and the line is a paragraph.
_MARGIN = r'(?:\A\ufeff)?[ \t]*'

#: One attribute block, brace to brace. Quoted values may contain a brace and
#: an escaped quote; a single nested brace pair is allowed for a braced span
#: written inside. A quote is never a bare character: the engine renders
#: `[x]{key=a"b}` as text, and a `"` both alternatives could take made an
#: unclosed run of quotes exponential (30 quotes, 2s, x2.6 per two more).
_ATTRS = (
    r'\{(?=[.:}\'"]|\#[\w-]+[\s}]|[A-Za-z][\w-]*(?:[=\s}]|$))(?:'
    r'"(?:[^"\\\n]|\\.)*"'
    r"|'(?:[^'\\\n]|\\.)*'"
    r'|\{[^{}\n]*\}'
    r'|(?!(?<=[{\s])[.#](?!\w[\w-]*[\s}]))[^{}\n"\']'
    r')*\}'
)

#: The block before the id and class check above. Only the reference definition
#: uses it: whether an invalid block there still leaves a definition is open in
#: markup-carve/carve#2122.
_ATTRS_UNCHECKED = _ATTRS.replace(r'(?!(?<=[{\s])[.#](?!\w[\w-]*[\s}]))', '')


#: The same block, as a STANDALONE ATTRIBUTE LINE, which may span lines:
#:
#:     {.a
#:     .b}
#:
#: The inline form deliberately cannot, because an unclosed inline `{` would
#: otherwise swallow the rest of the document.
_ATTRS_LINE = _ATTRS.replace(r'[^{}\n', r'[^{}')


def _label(depth=3):
    """A bracketed label that may itself contain ``depth`` levels of brackets.

    A regex cannot match arbitrarily balanced brackets, and a link label in
    practice nests a level or two (``[t[z]](/u)``). Bounding the nesting keeps
    the common shapes matching instead of stopping at the first inner bracket,
    which is what a naive ``\\[[^\\]]*\\]`` does.
    """
    inner = r'[^\[\]\\\n]|\\.'
    pattern = r'(?:' + inner + r')*'
    for _ in range(depth):
        pattern = r'(?:' + inner + r'|\[' + pattern + r'\])*'
    return r'\[' + pattern + r'\]'


_LABEL = _label()


#: A CONFORMING fence info string, as the guard on the pairing rules below.
#:
#: `code_fence_info` admits three shapes and nothing else - a language then an
#: optional "title" then an optional [label], or a title then an optional label,
#: or a label alone - and "a non-empty info string matches one of these three
#: shapes or it is an INVALID-FENCE FALLBACK". The fallback is not cosmetic: an
#: opener carrying a bare word after its language opens no block at all, and the
#: corpus renders the whole of it as a paragraph holding an unpartnered code
#: span. A pairing rule that ignored this would bury that paragraph as body.
#:
#: The ONE space before the info string is the grammar's, and is not a tab: five
#: corpus documents pin a tab or a second space there as a paragraph.
_FENCE_INFO = (
    r'(?:[A-Za-z0-9_+#./-]+(?: +"[^"\n]*")?(?: +\[[^\]\n]*\])?'
    r'|"[^"\n]*"(?: +\[[^\]\n]*\])?'
    r'|\[[^\]\n]*\])'
)


#: How many lines a fenced body may hold before the fence stops pairing. See
#: the fence rules below: this is the bound that keeps an unpairable opener from
#: costing a scan of the rest of the document.
_FENCE_BODY_LINES = 512


#: An ordered marker's value: a letter, or a roman run in ONE case (`Vim.` is
#: prose).
_ORDINAL = r'(?:\d+|[A-Za-z]|[ivxlcdm]+|[IVXLCDM]+)'

#: A run of block markers a line may carry before its content: bullets, ordered
#: markers and quote markers, in any nesting. A definition written after one is
#: still a definition (`- [t]: /t`), so the definition rules take this prefix
#: rather than losing the line to the marker rules below them.
_MARKER_RUN = (
    r'(?:(?:>+|(?:' + _ORDINAL + r'[.)]|[-*.])(?:' + _ATTRS + r')?)[ \t]+)*'
)

#: A line that opens some other block, which ends a definition list.
_OTHER_OPENER = (
    r'(?:#{1,6}[ \t]|`{3,}|~{3,}|:{3,}|>|\^[ \t]|\||%%|\*\[|\[[^\]\n]*\]:'
    r'|(?:[-*]|' + _ORDINAL + r'[.)]|\.)(?:' + _ATTRS + r')? )'
)


#: What a table row ends with: its closing pipe, optionally with a glued row
#: attribute block.
_ROW_END = r'[^\n]*\|(?:' + _ATTRS + r')?[ \t]*$'

#: A line that ends an open paragraph. List markers, a caption and a lone `+`
#: are not here: "list markers do not interrupt a paragraph", and the engine
#: reads `para` then `- x` as one paragraph.
_INTERRUPTER = (
    r'(?:#{1,6}[ \t]|`{3,}|~{3,}|:{2,}|>(?=[ \t]|$)|\|(?=[^\n]*\|)|%%'
    r'|\*\[[A-Za-z0-9]+\]: |\[[^\]\n]*\]:'
    r'|\{(?=[.:}\'"]|\#[\w-]+[\s}]|[A-Za-z][\w-]*(?:[=\s}]|$))'
    r'|(?:\*[ \t]*){3,}$|(?:-[ \t]*){3,}$|(?:_[ \t]*){3,}$)'
)

#: A newline that ends a paragraph: a blank line or an interrupting line follows.
_PARAGRAPH_BREAK = r'(?=[ \t]*(?:\n|\Z)|[ \t]*' + _INTERRUPTER + r')'


#: Where a top-level paragraph starts: a line with content at the start of the
#: document or after a blank line. Narrower than the engine, which also opens
#: one after a heading or a closed block, because a regex cannot see what the
#: line above was; a line it misses keeps the old reading, block rules first.
#: An image or display-math line with a caption under it is not one: that
#: paragraph is the caption's host, and the engine renders a figure.
_PARAGRAPH_START = (r'(?:\A|(?<=\n\n))(?=[^ \t\n])'
                    r'(?!(?:!\[|\$\$`)[^\n]*\n[ \t]*\^[ \t])')

#: A block a container's marker line may hold after the marker: `> - item`,
#: `- # H`, `: - item`. The rest of the line is then lexed as a block of its own.
_NESTED = (
    r'(?:#{1,6}[ \t]|>(?=[ \t]|$)|`{3,}|~{3,}|:{3,}|\|(?=[^\n]*\|[ \t]*$)'
    r'|\+(?=[ \t]*$)|(?:[-*]|' + _ORDINAL + r'[.)]|\.)(?:' + _ATTRS + r')?(?= +[ \t]*[^ \t\n]))'
)
_NESTED_TAIL = r'(?:([ \t]+)(?=' + _NESTED + r')([^\n]*))?'


#: Unicode `White_Space`, which ends a link destination. Python's `\s` also
#: matches U+001C-U+001F, which are destination characters.
_WHITE_SPACE = '\t\n\x0b\x0c\r \x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000'
_LINE_SPACE = _WHITE_SPACE.replace('\n', '')


def _extender_class():
    """Mn, Mc and Me, the variation selectors U+FE00-U+FE0F and U+200D, as a
    character class. Marks exist only in planes 0, 1 and 14."""
    ranges, start, last = [], None, None
    for plane in (range(0x300, 0x20000), range(0xE0000, 0xE1000)):
        for cp in plane:
            if (unicodedata.category(chr(cp)) in ('Mn', 'Mc', 'Me')
                    or 0xFE00 <= cp <= 0xFE0F or cp == 0x200D):
                if last is not None and cp == last + 1:
                    last = cp
                    continue
                if start is not None:
                    ranges.append((start, last))
                start = last = cp
    ranges.append((start, last))
    return '[' + ''.join(chr(a) if a == b else chr(a) + '-' + chr(b) for a, b in ranges) + ']'


#: A delimiter followed by one of these is the first code point of a larger
#: character and neither opens nor closes (CARVE-P3-025): the keycap `*`
#: U+FE0F U+20E3 is text. It follows each bare opener and closer, the delimiter
#: of every braced opener, and the `*` of `/*`.
_WHOLE = '(?!' + _extender_class() + ')'


#: Characters that can begin an inline construct. A run of anything else is
#: ordinary content and is emitted as ONE token - without this every content
#: character becomes its own token, which is both noisy and unusable to a
#: consumer asking whether a phrase carries a scope.
_INLINE_STARTERS = r'\\%!`${[^<>:@#*/_~=.\-(+'


def _plain_run(extra=''):
    """A run of content characters, excluding ``extra`` as well."""
    return r'[^\n' + _INLINE_STARTERS + extra + r']+'


#: Per-document indexes for `_Scan`, most recently used first. A `using()`
#: call lexes a substring, which is a different text, so several are live at
#: once; the bound only has to outlast that nesting.
_INDEXES = []
_INDEX_SLOTS = 16


def _indexes(text):
    for i, (held, found) in enumerate(_INDEXES):
        if held is text:
            if i:
                _INDEXES.insert(0, _INDEXES.pop(i))
            return found
    found = {}
    _INDEXES.insert(0, (text, found))
    del _INDEXES[_INDEX_SLOTS:]
    return found


def _positions(text, key, pattern):
    found = _indexes(text)
    hit = found.get(key)
    if hit is None:
        hit = found[key] = [m.start() for m in re.finditer(pattern, text, re.M)]
    return hit


def _line_end(text, at):
    """The offset of the first newline at or after ``at``, or ``len(text)``."""
    breaks = _positions(text, '\n', '\n')
    i = bisect.bisect_left(breaks, at)
    return breaks[i] if i < len(breaks) else len(text)


def _paragraph_end(text, at):
    """The offset of the newline that ends the paragraph holding ``at``."""
    breaks = _positions(text, 'paragraph', r'\n' + _PARAGRAPH_BREAK)
    i = bisect.bisect_left(breaks, at)
    return breaks[i] if i < len(breaks) else len(text)


#: A line that is a block of its own and ends with its line: a span opened on
#: it cannot run onto the next line, though that line continues no paragraph.
_ONE_LINE_BLOCK = (r'^[ \t]*(?:#{1,6}[ \t]|>|\^[ \t]|\||::|%%|\[\^?[^\]\n]*\]:|\*\[)'
                   r'[^\n]*(\n)')


def _block_end(text, at):
    """Where a span opened at ``at`` must close: its paragraph's end, or its
    line's end when the line is a block of its own (a heading, a quote line, a
    caption, a table row, a term or a definition)."""
    found = _indexes(text)
    ends = found.get('block')
    if ends is None:
        ends = set(_positions(text, 'paragraph', r'\n' + _PARAGRAPH_BREAK))
        ends.update(m.start(1) for m in re.finditer(_ONE_LINE_BLOCK, text, re.M))
        ends = found['block'] = sorted(ends)
    i = bisect.bisect_left(ends, at)
    return ends[i] if i < len(ends) else len(text)


def _limit(text, at, reach):
    if reach == 'block':
        return _block_end(text, at)
    return _paragraph_end(text, at) if reach == 'paragraph' else _line_end(text, at)


def _closers(text, rex, masked=False):
    """``(starts, ends)`` of every match of ``rex`` in ``text``, overlaps included.

    ``masked`` drops a match that starts inside an escape, a code span, a link
    or an autolink: `_masks` says why. ``'braced'`` keeps a match after an
    unclosed backtick run, ``'critic'`` does not, and ``'bare'`` also drops a
    match inside a braced span (`_braced_pairs`).
    """
    found = _indexes(text)
    key = (rex, masked)
    hit = found.get(key)
    if hit is None:
        starts, ends = [], []
        if masked:
            if masked == 'bare':
                spans = iter(_bare_masks(text))
            else:
                spans = zip(*_masks(text, masked == 'critic'))
            current = next(spans, None)
        for m in rex.finditer(text):
            at = m.start()
            if masked:
                while current is not None and current[1] <= at:
                    current = next(spans, None)
                if current is not None and current[0] <= at:
                    continue
            starts.append(at)
            ends.append(m.end(1))
        hit = found[key] = (starts, ends)
    return hit


class _Scan:
    """A rule whose closer is looked up in an index instead of scanned for.

    WHY. A rule spelled ``opener [^\\n]*? closer`` scans to the end of the line
    from every opener that has no closer, so a line of such openers is
    quadratic: 8000 characters of ``*a `` took 0.4s and doubling it four times
    that, and the CriticMarkup substitution, which scans twice, was cubic. The
    closers do not depend on which opener is asking, so they are found once per
    document and every opener does a binary search.

    ``rest`` completes ``opener`` into the rule's full pattern, which is matched
    with the found closer's end as ``endpos``, so the groups and the guards are
    the pattern's own. ``close`` names the closer: a pattern, or a tuple of
    patterns found one after the other. A closer starting fewer than ``least``
    characters past the opener is skipped, or with ``stop`` ends the search,
    which is how ``[^]\\n]+]`` reads: the FIRST `]` closes it or nothing does.

    A closer must start on the opener's line, or with ``reach='paragraph'``
    before the paragraph ends. ``masked`` skips closers inside a tighter
    construct. ``whole=False`` makes the rule a guard: it matches the opener
    alone, and only when a closer exists.
    """

    def __init__(self, opener, rest, close, least=0, stop=False, masked=False,
                 reach='line', whole=True):
        self.opener = opener
        self.pattern = opener + rest
        self.close = close if isinstance(close, tuple) else (close,)
        self.least = least
        self.stop = stop
        self.masked = masked
        self.reach = reach
        self.whole = whole
        self._compiled = {}

    def compile(self, flags):
        hit = self._compiled.get(flags)
        if hit is None:
            hit = self._compiled[flags] = self.matcher(flags).match
        return hit

    def matcher(self, flags):
        return _ScanMatcher(self, flags)


class _ScanMatcher:
    """A compiled `_Scan`. Pygments calls ``match(text, pos)`` like a regex's."""

    def __init__(self, scan, flags):
        self.scan = scan
        self.pattern = scan.pattern
        self.opener = re.compile(scan.opener, flags)
        self.full = re.compile(scan.pattern, flags)
        self.close = tuple(re.compile(r'(?=(' + c + r'))', flags) for c in scan.close)

    def end(self, text, opened):
        scan = self.scan
        at = opened.end()
        limit = _limit(text, at, scan.reach)
        for n, rex in enumerate(self.close):
            starts, ends = _closers(text, rex, scan.masked)
            floor = at + scan.least if n == 0 else at
            i = bisect.bisect_left(starts, at if scan.stop and n == 0 else floor)
            if i == len(starts) or starts[i] >= limit or starts[i] < floor:
                return None
            at = ends[i]
        return at

    def match(self, text, pos=0):
        opened = self.opener.match(text, pos)
        if opened is None:
            return None
        end = self.end(text, opened)
        if end is None:
            return None
        if not self.scan.whole:
            return opened
        return self.full.fullmatch(text, pos, end)


def _code_close(text, at, width, reach):
    """The end of the next backtick run of exactly ``width`` before ``reach``."""
    found = _indexes(text)
    runs = found.get('`')
    if runs is None:
        runs = found['`'] = {}
        for m in re.finditer('`+', text):
            runs.setdefault(m.end() - m.start(), []).append(m.start())
    starts = runs.get(width, ())
    i = bisect.bisect_left(starts, at)
    if i < len(starts) and starts[i] < _limit(text, at, reach):
        return starts[i] + width
    return None


class _CodeScan(_ScanMatcher):
    """A code span: its closer is the next backtick run of exactly its width.

    The runs are indexed by width once per document. The opener is a whole run
    too, so a run that finds no closer is never retried from inside itself.
    With ``unclosed`` a run with no partner runs to the end of its reach, which
    is how the engine reads one in a paragraph.
    """

    def end(self, text, opened):
        scan = self.scan
        at = opened.end()
        close = _code_close(text, at, len(opened.group(opened.re.groups)), scan.reach)
        if close is None and scan.unclosed:
            return _limit(text, at, scan.reach)
        return close


class _Code(_Scan):
    def __init__(self, opener, rest, reach='line', unclosed=False):
        super().__init__(opener, rest, (), reach=reach)
        self.unclosed = unclosed

    def matcher(self, flags):
        return _CodeScan(self, flags)


class _ContainerFence(_Scan):
    """A fence opened inside a container: on a list item's or a description's
    marker line, or behind a quote marker.

    A regex cannot hold a fence there. The closer of a fence in an item sits at
    the item's CONTENT COLUMN, the width of the marker line's prefix, which a
    pattern can match but not measure; and every line of a fence in a quote
    carries the quote's own prefix. So the body is walked line by line, as far
    as `_FENCE_BODY_LINES`: a line further left than the container's content,
    or a line that leaves the quote, ends the search with no pair, the same
    trade the top-level fence rule makes for an opener with no closer.
    """

    def __init__(self, opener, rest, quoted=False):
        super().__init__(opener, rest, ())
        self.quoted = quoted

    def matcher(self, flags):
        return _ContainerFenceScan(self, flags)


class _ContainerFenceScan(_ScanMatcher):

    def __init__(self, scan, flags):
        super().__init__(scan, flags)
        self.walks = {}

    def end(self, text, opened):
        run, char = opened.group(5), opened.group(6)
        if self.scan.quoted:
            prefix = opened.group(2) + opened.group(3) + opened.group(4)
            key = (prefix, char, len(run))
        else:
            key = (opened.end(4) - opened.start(2), char, len(run))
        walk = self.walks.get(key)
        if walk is None:
            closer = re.escape(char) + r'{%d,}[ \t]*(?=\n|\Z)' % len(run)
            if self.scan.quoted:
                body = r'[ \t]*>{%d}[^\n]*\n' % len(opened.group(3))
                closer = re.escape(prefix) + closer
            else:
                # A blank line, or one with content at or past the column; the
                # two cannot both take a line, so the search cannot backtrack.
                body = r'[ \t]*\n|[ \t]{%d}(?![ \t]*\n)[^\n]*\n' % key[0]
                closer = r'[ \t]{%d}' % key[0] + closer
            walk = self.walks[key] = re.compile(
                r'(?:%s){0,%d}?%s' % (body, _FENCE_BODY_LINES, closer)).match
        found = walk(text, opened.end())
        return found.end() if found else None


#: A fence info string a container fence may carry: a raw format, or a
#: conforming code fence info string.
_ANY_FENCE_INFO = r'(?= ?(?:=[a-zA-Z][\w+.-]*|{0})?[ \t]*$)'.format(_FENCE_INFO)

#: A fence on a list item's marker line, its closer at the item's content column.
_ITEM_FENCE = _ContainerFence(
    r'^((?:\A\ufeff)?)([ \t]*)((?:[-*]|' + _ORDINAL + r'[.)]|\.)(?:' + _ATTRS + r')?)'
    r'( +)((`|~)\6{2,})' + _ANY_FENCE_INFO
    + r'([ \t]*)(=[a-zA-Z][\w+.-]*|[a-zA-Z][\w+#.-]*)?([^\n]*)(\n)',
    r'((?:[^\n]*\n)*?)([ \t]*)(\5\6*)([ \t]*)')

#: The same on a description's `:` line.
_DESCRIPTION_FENCE = _ContainerFence(
    r'^((?:\A\ufeff)?)([ \t]*)(:)'
    r'( +)((`|~)\6{2,})' + _ANY_FENCE_INFO
    + r'([ \t]*)(=[a-zA-Z][\w+.-]*|[a-zA-Z][\w+#.-]*)?([^\n]*)(\n)',
    r'((?:[^\n]*\n)*?)([ \t]*)(\5\6*)([ \t]*)')

#: A fence behind a quote marker; every line to its closer carries the marker.
_QUOTED_FENCE = _ContainerFence(
    r'^((?:\A\ufeff)?)([ \t]*)(>+)([ \t]?)((`|~)\6{2,})' + _ANY_FENCE_INFO
    + r'([ \t]*)(=[a-zA-Z][\w+.-]*|[a-zA-Z][\w+#.-]*)?([^\n]*)(\n)',
    r'((?:[^\n]*\n)*?)([ \t]*)(>+)([ \t]?)(\5\6*)([ \t]*)',
    quoted=True)


#: The tight inline constructs, shared by their rules and by `_masks`.
_FOOTNOTE_REF = _Scan(r'(\[\^)', r'([^\]\n]+)(\])', r'\]', stop=True)
_CITATION = _Scan(r'(\[)(?=\+?@)', r'(\+?@[^\]\n]+)(\])', r'\]', stop=True)
_IMAGE = _Scan(r'(!' + _LABEL + r')(\()', r'([^)\n]*)(\))', r'\)', stop=True)
_IMAGE_REF = r'(!' + _LABEL + r')(' + _LABEL + r')'
_LINK = _Scan(r'(' + _LABEL + r')(\()', r'([^)\n]*)(\))', r'\)', stop=True)
_LINK_REF = r'(' + _LABEL + r')(' + _LABEL + r')'
_LINK_ATTRS = r'(' + _LABEL + r')(?=' + _ATTRS + r')'
_CROSS_REFERENCE = r'(</)(#[\w-]+)(>)'
_AUTOLINK = _Scan(r'(<)', r'([a-zA-Z][\w+.-]*:[^>\s]+|[^>\s@]+@[^>\s]+)(>)', r'[>\s]',
                  stop=True)

_MASK_AT = re.compile(r'\\|`|<|!?\[')
_ESCAPE = re.compile(r'\\[!-/:-@\[-`{-~]')
_TIGHT_LABELS = None


def _tight_labels():
    global _TIGHT_LABELS
    if _TIGHT_LABELS is None:
        def plain(pattern):
            return re.compile(pattern, re.M).match
        _TIGHT_LABELS = (
            (_IMAGE.compile(re.M), plain(_IMAGE_REF)),
            (_FOOTNOTE_REF.compile(re.M), _CITATION.compile(re.M), _LINK.compile(re.M),
             plain(_LINK_REF), plain(_LINK_ATTRS)),
            (plain(_CROSS_REFERENCE), _AUTOLINK.compile(re.M)),
        )
    return _TIGHT_LABELS


def _tight(text, at, unclosed):
    """``(start, end)`` of the tight construct starting at ``at``, or None."""
    char = text[at]
    if char == '\\':
        m = _ESCAPE.match(text, at)
        return m and m.span()
    if char == '`':
        if at and text[at - 1] == '`':
            return None
        if text.startswith('```', at) and not text[text.rfind('\n', 0, at) + 1:at].strip():
            # A fence line, which the block rules read; it is not a code span.
            return None
        end = at
        while end < len(text) and text[end] == '`':
            end += 1
        close = _code_close(text, end, end - at, 'paragraph')
        if close is None:
            return (at, _block_end(text, end)) if unclosed else None
        return at, close
    images, links, angles = _tight_labels()
    if char == '<':
        tried = angles
    elif char == '!':
        for match in images:
            m = match(text, at)
            if m:
                return m.start(), m.end()
        at += 1
        tried = links
    else:
        tried = links
    for match in tried:
        m = match(text, at)
        if m:
            return m.start(), m.end()
    return None


def _masks(text, unclosed):
    """``(starts, ends)`` of every construct a delimiter inside cannot close.

    An escaped delimiter is literal, and a code span, a link, an image, a
    reference and an autolink bind tighter than emphasis: the engine renders
    `*a [b*](u)` as a literal `*a` and a link, `{=a \\=} b=}` as one mark, and
    `*a `b*` c*` as one strong holding a code span. Found once per document,
    left to right, so a construct inside another one is not a second mask.

    A backtick run with no partner masks the rest of its block from a BARE
    closer (``unclosed``), because the run reaches the end of its paragraph:
    `*a ` b*` is a literal `*a` and a code span. A braced closer still closes
    over it, `{*`a*}` being a strong holding an unclosed code span (corpus 12).
    """
    found = _indexes(text)
    key = ('mask', unclosed)
    hit = found.get(key)
    if hit is None:
        starts, ends = [], []
        reach = 0
        for m in _MASK_AT.finditer(text):
            if m.start() < reach:
                continue
            span = _tight(text, m.start(), unclosed)
            if span:
                starts.append(span[0])
                ends.append(span[1])
                reach = span[1]
        hit = found[key] = (starts, ends)
    return hit


#: A braced opener, and the closer of each kind.
_BRACED_OPENER = re.compile(r'\{([*/_~^,=+-])' + _WHOLE)
_BRACED_CLOSER = re.compile(r'([*/_~^,=+-])\}')


def _braced_pairs(text):
    """``{opener offset: span end}`` for every braced span in ``text``.

    A braced span nests, its own kind too: the engine renders `{*a {*b*} c*}`
    as a strong inside a strong, `{*a {*b*}` as a literal `{*a` and a strong,
    and `{*a {/b*} c/}` as a literal `{*a` and an italic holding `b*} c`. That
    is the reading of pairing the openers from the LAST one back: each takes
    the first closer of its kind that no span already paired to its right
    holds, and its own span then holds every closer inside it. A closer inside
    an escape, a code span or a link is no closer (`_masks`), and a span ends
    in its block. Each closer is skipped at most once, so this is linear.
    """
    found = _indexes(text)
    hit = found.get('braced')
    if hit is not None:
        return hit
    mask_starts, mask_ends = _masks(text, False)
    notes = _comment_spans(text)
    note_starts = [start for start, _ in notes]

    def masked(at):
        i = bisect.bisect_right(mask_starts, at) - 1
        if i >= 0 and at < mask_ends[i]:
            return True
        i = bisect.bisect_right(note_starts, at) - 1
        return i >= 0 and at < notes[i][1]

    closers = {}
    for m in _BRACED_CLOSER.finditer(text):
        if not masked(m.start()):
            closers.setdefault(m.group(1), []).append(m.start())
    # `skip[kind][i]` points past closers that are used or held by a span.
    skip = {kind: list(range(len(at) + 1)) for kind, at in closers.items()}

    def free(kind, i):
        nxt = skip[kind]
        root = i
        while nxt[root] != root:
            root = nxt[root]
        while nxt[i] != root:
            nxt[i], i = root, nxt[i]
        return root

    pairs = {}
    openers = [m for m in _BRACED_OPENER.finditer(text) if not masked(m.start())]
    for m in reversed(openers):
        kind, at = m.group(1), m.start()
        positions = closers.get(kind)
        if not positions:
            continue
        i = free(kind, bisect.bisect_left(positions, at + 3))
        if i == len(positions) or positions[i] >= _block_end(text, at):
            continue
        close = positions[i]
        pairs[at] = close + 2
        for other, places in closers.items():
            j = free(other, bisect.bisect_right(places, at))
            while j < len(places) and places[j] <= close:
                skip[other][j] = j + 1
                j = free(other, j + 1)
    found['braced'] = pairs
    return pairs


def _comment_spans(text):
    """``[(start, end)]`` of the comments a braced delimiter inside is not
    one: `{#...#}` and `{%...%}`, and a trailing `%%` comment to its line end.
    The engine renders `{*a {# {* x #} b*}` as one strong holding the comment.
    The braced en dash `{--}` is here too: it is one token, neither an opener
    nor a closer.
    """
    mask_starts, mask_ends = _masks(text, False)
    spans, reach = [], 0
    for m in re.finditer(r'\{--\}|\{[#%]' + _WHOLE + r'|%%', text):
        at = m.start()
        if at < reach:
            continue
        i = bisect.bisect_right(mask_starts, at) - 1
        if i >= 0 and at < mask_ends[i]:
            continue  # escaped, or inside a code span: no comment opens here
        if m.group() == '{--}':
            end = m.end()
        elif m.group() == '%%':
            end = _line_end(text, at)
        else:
            close = '#}' if m.group() == '{#' else '%}'
            limit = _line_end(text, at) if close == '#}' else _block_end(text, at)
            starts = _positions(text, close, re.escape(close))
            i = bisect.bisect_left(starts, at + 2)
            if i == len(starts) or starts[i] >= limit:
                continue
            end = starts[i] + 2
        spans.append((at, end))
        reach = end
    return spans


def _bare_masks(text):
    """The masks of a bare closer: `_masks`, and every braced span, which a
    bare span cannot close inside (`*a {=b*=} c*` is one strong)."""
    found = _indexes(text)
    hit = found.get('baremask')
    if hit is None:
        spans = list(zip(*_masks(text, True)))
        spans += _braced_pairs(text).items()
        hit = found['baremask'] = sorted(spans)
    return hit


class _BracedScan(_ScanMatcher):
    """A braced span, its closer looked up in `_braced_pairs`."""

    def end(self, text, opened):
        return _braced_pairs(text).get(opened.start())


class _Braced(_Scan):
    def __init__(self, opener, rest):
        super().__init__(opener, rest, ())

    def matcher(self, flags):
        return _BracedScan(self, flags)


#: A fence body read verbatim, and one behind a quote marker. Each is also the
#: placeholder `_fenced` swaps for the language's own lexer.
_BODY = using(this, state='fencebody')
_QUOTED_BODY = using(this, state='quotedfencebody')

_CALLOUT = re.compile(r'<\d+>')
_QUOTE_MARKER = re.compile(r'^[ \t]*>+[ \t]?', re.M)

#: Language name -> its lexer, or None where Pygments has none.
_LANGUAGES = {}


class _DelimitedLexer(RegexLexer):
    tokens = {}

    @classmethod
    def for_separator(cls, separator):
        """Every field is typed (the separator is Operator.Word, a saturated color in the default style): the header record is Generic.Strong, an
        unquoted field String.Other, a quoted one String, `""` String.Escape."""
        escaped = re.escape(separator)
        states = {}

        def build(prefix, field, enter):
            on_newline = lambda pops: pops + enter
            states[prefix + 'root'] = [
                (escaped, Operator.Word),
                (r'"', String, prefix + 'quoted'),
                (r'\n', Text, *enter),
                (r'[^' + escaped + r'\n"]+', field, prefix + 'plain'),
            ]
            states[prefix + 'plain'] = [
                (escaped, Operator.Word, '#pop'),
                (r'\n', Text, on_newline(('#pop',))),
                (r'[^' + escaped + r'\n]+', field),
            ]
            states[prefix + 'quoted'] = [
                (r'""', String.Escape),
                (r'"', String, prefix + 'afterquote'),
                (r'[^\"]+', String),
            ]
            states[prefix + 'afterquote'] = [
                (escaped, Operator.Word, '#pop:2'),
                (r'\n', Text, on_newline(('#pop', '#pop'))),
                (r'[^' + escaped + r'\n]+', field),
            ]

        build('', Generic.Strong, ('rowsroot',))
        build('rows', String.Other, ())
        return states


class CsvLexer(_DelimitedLexer):
    name = 'CSV'
    aliases = ['csv']
    tokens = _DelimitedLexer.for_separator(',')


class TsvLexer(_DelimitedLexer):
    name = 'TSV'
    aliases = ['tsv']
    tokens = _DelimitedLexer.for_separator('\t')


def _language(name):
    hit = _LANGUAGES.get(name, False)
    if hit is False:
        try:
            if name == 'csv':
                hit = CsvLexer(stripnl=False, ensurenl=False)
            elif name == 'tsv':
                hit = TsvLexer(stripnl=False, ensurenl=False)
            else:
                hit = get_lexer_by_name(name, stripnl=False, ensurenl=False)
        except ClassNotFound:
            hit = None
        _LANGUAGES[name] = hit
    return hit


def _delegated(language, quoted):
    """A body action lexing the body with ``language``.

    The code callout markers, and behind a quote each line's marker, are taken
    out before the language's lexer sees the code and put back as their own
    tokens: a `<1>` is Carve, and `> ` is the quote's, in any language.
    """
    def action(lexer, match, ctx=None):
        text = match.group()
        marks = [(m.start(), m.end(), Name.Constant) for m in _CALLOUT.finditer(text)]
        if quoted:
            marks += [(m.start(), m.end(), Punctuation)
                      for m in _QUOTE_MARKER.finditer(text) if m.end() > m.start()]
        code, insertions, at, removed = [], [], 0, 0
        for start, end, ttype in sorted(marks):
            code.append(text[at:start])
            insertions.append((start - removed, [(0, ttype, text[start:end])]))
            removed += end - start
            at = end
        code.append(text[at:])
        base = match.start()
        tokens = language.get_tokens_unprocessed(''.join(code))
        for index, ttype, value in do_insertions(insertions, tokens):
            yield base + index, ttype, value
    return action


def _fenced(lang, *actions):
    """``bygroups(*actions)``, with the body read by the language named in
    group ``lang`` when Pygments knows it, as Pygments' own Markdown lexer
    does. A raw block's `=FORMAT` names its language the same way. Off with
    the ``handlecodeblocks`` option, and for a language Pygments does not know.
    """
    verbatim = bygroups(*actions)

    def action(lexer, match):
        name = (match.group(lang) or '').lstrip('=')
        language = _language(name) if name and lexer.handlecodeblocks else None
        if language is None:
            return verbatim(lexer, match)
        return bygroups(*[
            _delegated(language, quoted=part is _QUOTED_BODY)
            if part is _BODY or part is _QUOTED_BODY else part
            for part in actions])(lexer, match)
    return action


def _silent(lexer, match):
    """The action of a rule that only changes state: no empty token."""
    return iter(())


_ROW_LINE = re.compile(
    r'[ \t]*' + _MARKER_RUN + r'\|[^\n]*\|(?:' + _ATTRS + r')?[ \t]*$')
_PLUS_ROW_LINE = re.compile(r'[ \t]*\+[ \t][^\n]*\|(?:' + _ATTRS + r')?[ \t]*$')


def _line_above(text, start):
    """The line ending just before offset `start`, or None at the first line."""
    if start == 0:
        return None
    return text[text.rfind('\n', 0, start - 1) + 1:start - 1]


def _decisions(lexer, text):
    """Per-document record of each `+ ... |` line's reading, keyed by line offset.

    Reusing the reading of the nearest `+` line above keeps the lookback linear.
    """
    memo = getattr(lexer, '_plus_decisions', None)
    if memo is None or memo[0] is not text:
        memo = (text, {})
        lexer._plus_decisions = memo
    return memo[1]


_BLOCK_OPENER = re.compile(
    r'(?:(?P<item>(?:[-*](?:' + _ATTRS + r')?[ \t]+(?:\[[ xX_>?-]\][ \t]+)?'
    r'|(?:' + _ORDINAL + r'[.)]|\.)(?:' + _ATTRS + r')?[ \t]+))'
    r'|(?P<quote>>(?:[ \t]|$))|(?P<holder>(?:::?|\[\^[^\]\n]+\]:)[ \t]+))')
_BLOCK_LINE = re.compile(r'(?:`{3,}|~{3,}|:{3,}|#{1,6}(?:[ \t]|$)|\|)')


def _columns(text, start=0, col=0):
    """Visual column of each offset from `start`, with tab stops of four."""
    cols = []
    for ch in text[start:]:
        cols.append(col)
        col = col + 4 - col % 4 if ch == '\t' else col + 1
    cols.append(col)
    return cols


def _unquote(line, depth):
    """Strip `depth` quote prefixes: (offset, column) of what follows, or None."""
    at, col = 0, 0
    for _ in range(depth):
        while at < len(line) and line[at] in ' \t' and col < 3:
            col = col + 4 - col % 4 if line[at] == '\t' else col + 1
            at += 1
        if at >= len(line) or line[at] != '>' or line[at + 1:at + 2] not in ('', ' '):
            return None
        at, col = at + 1, col + 1
        if at < len(line) and line[at] in ' \t':
            col = col + 4 - col % 4 if line[at] == '\t' else col + 1
            at += 1
    return at, col


def _quote_depth(line):
    depth = 0
    while _unquote(line, depth + 1) is not None:
        depth += 1
    return depth


def _shape(line, depth):
    """(indent, [(column, kind)]) of a line read inside `depth` quotes, or None."""
    stripped = _unquote(line, depth)
    if stripped is None:
        return None
    at, base = stripped
    cols = _columns(line, at, base)
    rest = line[at:]
    lead = len(rest) - len(rest.lstrip(' \t'))
    if lead == len(rest):
        return cols[lead], None
    openers, pos = [], lead
    while True:
        m = _BLOCK_OPENER.match(rest, pos)
        if not m or m.end() == pos:
            break
        openers.append((cols[pos] - base, m.lastgroup))
        pos = m.end()
        while pos < len(rest) and rest[pos] in ' \t':
            pos += 1
    return cols[lead] - base, openers


def _open_columns(lines, row, depth, seen):
    """Marker columns of the containers still open at `row`, read inside `depth` quotes.

    A list item stays open across a blank line; a quote, a description or a
    footnote does not. A line left of a container's marker column closes it,
    unless it is a lazy paragraph line.
    """
    if (row, depth) in seen:
        return seen[row, depth]
    found, ceiling, blank = [], float('inf'), False
    for j in range(row - 1, -1, -1):
        shape = _shape(lines[j], depth)
        if shape is None:
            break
        indent, openers = shape
        plus = _LONE_PLUS.match(lines[j], _unquote(lines[j], depth)[0])
        if plus and _plus_reading(lines, seen, j, plus.start(1), depth):
            # The lines below were attached at the `+` column: that container
            # stays open, the ones right of it close.
            ceiling = indent + 1 if ceiling >= indent else ceiling
            if (j, depth) in seen:
                found += [(c, kind) for c, kind in seen[j, depth]
                          if c < ceiling and (kind == 'item' or not blank)]
                break
            continue
        if openers is None:
            blank = True
            continue
        if openers:
            for col, kind in openers:
                if col < ceiling and (kind == 'item' or not blank):
                    found.append((col, kind))
            ceiling = min(ceiling, openers[0][0])
        else:
            above = _shape(lines[j - 1], depth) if j else None
            lazy = (not _BLOCK_LINE.match(lines[j], len(lines[j]) - len(lines[j].lstrip(' \t>')))
                    and above is not None and above[1] is not None)
            if not lazy:
                ceiling = min(ceiling, indent)
        if ceiling <= 0:
            break
        # A row read before already holds everything above it: stay linear.
        if (j, depth) in seen:
            found += [(c, kind) for c, kind in seen[j, depth]
                      if c < ceiling and (kind == 'item' or not blank)]
            break
    # Unique: a row inherits its neighbor's list, which must not grow per row.
    found = list(dict.fromkeys(found))
    seen[row, depth] = found
    return found


def _lines(lexer, text):
    """The document's lines, their start offsets and a lookback memo, once per text.

    Keyed by identity: a `using` sub-lexer runs on the same lexer with a
    substring, and must not evict the outer document.
    """
    memo = getattr(lexer, '_plus_lines', None)
    if memo is None:
        memo = lexer._plus_lines = {}
    entry = memo.get(id(text))
    if entry is None or entry[0] is not text:
        if len(memo) > 8:
            memo.clear()
        lines = text.split('\n')
        starts = [0]
        for line in lines:
            starts.append(starts[-1] + len(line) + 1)
        entry = memo[id(text)] = (text, lines, starts, {})
    return entry[1:]


_LONE_PLUS = re.compile(r'[ \t]*(\+)[ \t]*$')


def _plus_reading(lines, seen, row, plus_at, depth):
    """Is the lone `+` at line offset `plus_at` of `row`, read inside `depth` quotes, a marker?

    The relative rule (markup-carve/carve#3445): the `+` stands at an open
    container's marker column, and the next line starts a block at that same
    column; a list item there is a sibling, and leaves the `+` as text, only
    when that container is a list item. Right behind open quote prefixes carve-js
    takes no quote as that block.
    """
    key = ('plus', row, depth)
    if key in seen:
        return seen[key]
    seen[key] = False
    line = lines[row]
    stripped = _unquote(line, depth)
    if stripped is None:
        return False
    at, base = stripped
    column = _columns(line, at, base)[plus_at - at] - base
    kinds = {kind for c, kind in _open_columns(lines, row, depth, seen) if c == column}
    if not kinds:
        return False
    if row + 1 >= len(lines):
        return False
    follower = _shape(lines[row + 1], depth)
    if follower is None or follower[1] is None or follower[0] != column:
        return False
    first = follower[1][0] if follower[1] else None
    attaches = not ('item' in kinds and first == (column, 'item')) and not (depth and first == (0, 'quote'))
    seen[key] = attaches
    return attaches


def _opener_follows(lines, row, depth, column):
    """Does a first-block `+` behind `depth` new quote prefixes take the next line?

    The next line must start a block flush with the quote, outside it (a line
    that continues the quote keeps the `+` as text), and not a list item.
    """
    if row + 1 >= len(lines):
        return False
    line = lines[row + 1]
    shape = _shape(line, min(_quote_depth(line), depth - 1))
    if shape is None or shape[1] is None or _quote_depth(line) >= depth:
        return False
    return shape[0] <= column and not (shape[1] and shape[1][0][1] == 'item')


def _continuation_marker(lexer, match):
    margin, plus, rest = match.group(1, 2, 3)
    lines, starts, seen = _lines(lexer, match.string)
    row = bisect.bisect_right(starts, match.start()) - 1
    attaches = _plus_reading(lines, seen, row, match.start(2) - match.start(), 0)
    yield match.start(1), Text, margin
    yield match.start(2), Operator if attaches else Text, plus
    yield match.start(3), Text, rest


def _quoted_plus(lexer, match):
    """A `+` alone behind quote prefixes.

    A prefix that opens a quote makes it a first-block marker; behind the
    prefixes of quotes already open it is a separate-line marker for them.
    """
    text = match.string
    margin, prefix, plus, rest = match.group(1, 2, 3, 4)
    lines, starts, seen = _lines(lexer, text)
    row = bisect.bisect_right(starts, match.start()) - 1
    depth = prefix.count('>')
    open_depth = 0
    for j in range(row - 1, -1, -1):
        shape = _shape(lines[j], 0)
        if shape[1] is None:
            break
        open_depth = _quote_depth(lines[j])
        if open_depth or shape[1] or _BLOCK_LINE.match(lines[j].lstrip(' \t')):
            break
    if depth > open_depth:
        indent = _columns(margin)[-1]
        # Only right after the last prefix: `>  +` is quote text.
        attaches = (re.search(r'>[ \t]?$', prefix) is not None
                    and (indent == 0 or any(c < indent for c, kind in _open_columns(lines, row, 0, seen)
                                            if kind == 'item'))
                    and _opener_follows(lines, row, depth, indent))
    else:
        attaches = _plus_reading(lines, seen, row, match.start(3) - match.start(), depth)
    yield match.start(1), Text, margin
    for part in re.finditer(r'>|[^>]+', prefix):
        yield match.start(2) + part.start(), Punctuation if part.group() == '>' else Text, part.group()
    yield match.start(3), Operator if attaches else Text, plus
    yield match.start(4), Text, rest


def _hosted_quote_plus(lexer, match):
    """`- > +`: a first-block `+` behind a quote that a list item opens on the same line.

    It takes the next line when that line starts a block other than a list item
    at column 0 of the line's quote level, at the line's own indent, or at the
    column of the quote that owns the `+` (carve#3421, corpus 630 to 656).
    """
    margin, outer, run, quotes, plus, rest = match.group(1, 2, 3, 4, 5, 6)
    lines, starts, seen = _lines(lexer, match.string)
    row = bisect.bisect_right(starts, match.start()) - 1
    attaches = False
    if row + 1 < len(lines):
        line, follower = lines[row], lines[row + 1]
        depth = outer.count('>')
        cols = _columns(line)
        base = cols[len(margin) + len(outer)] if depth else 0
        quote_at = len(margin) + len(outer) + len(run) + len(quotes) - 2
        eligible = {0, cols[len(margin) + len(outer)] - base, cols[quote_at] - base}
        shape = _shape(follower, min(_quote_depth(follower), depth))
        if shape is not None and shape[1] is not None and not _LONE_PLUS.fullmatch(follower.lstrip(' \t>')):
            attaches = shape[0] in eligible and not (shape[1] and shape[1][0][1] == 'item')
    yield match.start(1), Text, margin
    for part in re.finditer(r'>|[^>]+', outer):
        yield match.start(2) + part.start(), Punctuation if part.group() == '>' else Text, part.group()
    for part in re.finditer(r'(\[[ xX_>?-]\])|(' + _ORDINAL + r'[.)](?:' + _ATTRS + r')?|\.(?:' + _ATTRS + r')?)|[-*](?:' + _ATTRS + r')?| ', run):
        kind = Name.Constant if part.group(1) else Number.Integer if part.group(2) else Text if part.group() == ' ' else Punctuation
        yield match.start(3) + part.start(), kind, part.group()
    for part in re.finditer(r'>| ', quotes):
        yield match.start(4) + part.start(), Punctuation if part.group() == '>' else Text, part.group()
    yield match.start(5), Operator if attaches else Text, plus
    yield match.start(6), Text, rest


_TERM_LINE = re.compile(r'[ \t]*::[ \t]')
_DESCRIPTION_LINE = re.compile(r'[ \t]*:[ \t]')


def _description_marker(lexer, match):
    """A `:` left of its term's `::` column ends the list and reads as text (carve#3458)."""
    margin, colon = match.group(1), match.group(2)
    lines, starts, seen = _lines(lexer, match.string)
    row = bisect.bisect_right(starts, match.start()) - 1
    column = _columns(margin)[-1]
    term = None
    below = None
    for j in range(row - 1, -1, -1):
        line = lines[j]
        if not line.strip():
            continue
        indent = _columns(line[:len(line) - len(line.lstrip(' \t'))])[-1]
        if _TERM_LINE.match(line):
            term = indent if term is None else min(term, indent)
            if term <= column:
                break
        elif _DESCRIPTION_LINE.match(line):
            # An earlier separator at this column with no term between reads the same.
            if term is None and indent == column and ('desc', j) in seen:
                below = seen['desc', j]
                break
        elif term is not None and indent < term:
            break
    if below is None:
        below = term is not None and column < term
    seen['desc', row] = below
    yield match.start(1), Text, margin
    yield match.start(2), Text if below else Punctuation, colon
    if match.group(3) is not None:
        yield match.start(3), Text, match.group(3)
        for at, token, value in lexer.get_tokens_unprocessed(match.group(4), ('root', 'inline' if below else 'nested')):
            yield match.start(4) + at, token, value


_FLUSH_BLOCK = re.compile(
    r'(?![-*](?:' + _ATTRS + r')?[ \t]|(?:' + _ORDINAL + r'[.)]|\.)(?:' + _ATTRS + r')?[ \t])[^ \t\n]')


def _definition_plus(lexer, match):
    """`[^a]: +` is a first-block marker over a flush-left block that is not a list item."""
    text = match.string
    end = text.find('\n', match.end())
    yield match.start(), Punctuation if end >= 0 and _FLUSH_BLOCK.match(text, end + 1) else Text, '+'


def _continuation_row(lexer, match):
    """A `+ ... |` line is a row only directly under a table row."""
    margin, plus, rest = match.group(1, 2, 3)
    decided = _decisions(lexer, match.string)
    above = _line_above(match.string, match.start())
    if above is None:
        is_row = False
    elif _PLUS_ROW_LINE.match(above):
        is_row = decided.get(match.start() - len(above) - 1, False)
    else:
        is_row = _ROW_LINE.match(above) is not None
    decided[match.start()] = is_row
    yield match.start(1), Text, margin
    yield match.start(2), Punctuation if is_row else Text, plus
    stack = ('root', 'tablerow') if is_row else ('root', 'paragraph')
    for index, token, value in lexer.get_tokens_unprocessed(rest, stack):
        yield match.start(3) + index, token, value


def _escaped(text, at):
    """Whether the character at `at` follows an odd run of backslashes."""
    run = 0
    while at - run > 0 and text[at - run - 1] == '\\':
        run += 1
    return run % 2 == 1


def _bracket_closers(text, start):
    """Which `]` and `)` on the line at `start` may take an attribute block.

    Only a span, link or image closer takes one. A `]` closes the nearest open
    unescaped `[`; with none open it attaches unless an escaped `\\[` stands
    unclosed before it, since a span may have opened on an earlier line. A `)`
    must close a link destination, so its `(` follows such a `]`. One forward
    pass, so a line costs linear time however many blocks it holds.
    """
    end = text.find('\n', start)
    end = len(text) if end < 0 else end
    closers = {}
    brackets = []
    parens = []
    escaped_opener = False
    for i in range(start, end):
        c = text[i]
        if c not in '[]()':
            continue
        if _escaped(text, i):
            if c == '[' and not brackets:
                escaped_opener = True
            continue
        if c == '[':
            brackets.append(i)
        elif c == ']':
            if brackets:
                brackets.pop()
                closers[i] = True
            else:
                closers[i] = not escaped_opener
                escaped_opener = False
        elif c == '(':
            parens.append(i)
        elif parens:
            o = parens.pop()
            closers[i] = o > start and closers.get(o - 1, False) and text[o - 1] == ']'
        else:
            closers[i] = False
    return closers


class _ScanMeta(RegexLexerMeta):
    """Compiles a `_Scan` rule to its matcher and every other rule as Pygments does."""

    def _process_regex(cls, regex, rflags, state):
        if isinstance(regex, _Scan):
            return regex.compile(rflags)
        return super()._process_regex(regex, rflags, state)



class CarveLexer(RegexLexer, metaclass=_ScanMeta):
    """Lexer for the Carve markup language."""

    name = 'Carve'
    url = 'https://markup-carve.github.io/carve/'
    aliases = ['carve', 'crv']
    filenames = ['*.crv', '*.carve']
    mimetypes = ['text/x-carve']
    version_added = '0.1'

    # MULTILINE so that `^` anchors a block opener to the start of ITS line
    # rather than the start of the document - without it every block rule here
    # is dead past the first line. No IGNORECASE: Carve is case-sensitive, and
    # `::: NOTE` is not the `note` admonition.
    flags = re.MULTILINE

    def __init__(self, **options):
        # WHY THE TWO PYGMENTS DEFAULTS ARE TURNED OFF. `Lexer` strips leading
        # and trailing newlines from a document and appends one if it is
        # missing. Both are reasonable for a programming language and neither
        # is for Carve, where whitespace is syntax: a fence "keeps the blank
        # line at the end of its content", and the spec is explicit that "zero
        # payload lines contribute nothing; one blank payload line contributes
        # one newline. An implementation MUST NOT encode those two source
        # shapes identically." Stripping a LEADING newline would move every
        # line of the document, and appending a trailing one invents a line the
        # author did not write. With them on, three corpus documents came out
        # of `get_tokens` shorter than they went in
        # (markup-carve/pygments-carve#33).
        #
        # `setdefault`, not assignment: a caller who asks for the Pygments
        # behaviour still gets it.
        options.setdefault('stripnl', False)
        options.setdefault('ensurenl', False)
        super().__init__(**options)
        # The Markdown lexer's option, with its default: a fence naming a
        # language Pygments knows is highlighted in that language.
        self.handlecodeblocks = get_bool_opt(options, 'handlecodeblocks', True)

    def get_tokens_unprocessed(self, text, stack=('root',)):
        # The inline attribute rule matches `{...}` anywhere; after plain
        # brackets such as `(a){.c}` or `\[x]{.c}` the engine keeps it as text.
        start = end = -1
        closers = {}
        for index, token, value in super().get_tokens_unprocessed(text, stack):
            if (token is Name.Attribute and index and value.startswith('{')
                    and text[index - 1] in ')]'):
                if not start <= index - 1 < end:
                    start = text.rfind('\n', 0, index) + 1
                    end = text.find('\n', index)
                    end = len(text) if end < 0 else end
                    closers = _bracket_closers(text, start)
                if not closers.get(index - 1, False):
                    token = Text
            yield index, token, value

    tokens = {
        'root': [
            include('block'),
        ],

        # ------------------------------------------------------------------
        # Block level
        # ------------------------------------------------------------------
        'block': [
            # Front matter, matched WHOLE, only at the very start of the
            # document. `\A` is what keeps a `---yaml` line mid-document from
            # opening one, and the required closer is what keeps a state from
            # having to span the body - a state cannot, because none of its
            # rules matched a bare newline and Pygments resets the stack at
            # every line it cannot match (markup-carve/pygments-carve#32).
            #
            # A closer is REQUIRED here for the same reason the grammar
            # requires one: `frontmatter` carries a `&(...)` guard demanding a
            # closing `---` ahead, and "with no closer the guard fails, so a
            # bare `---` at document start is an ordinary thematic break". The
            # thematic-break rule below is what then takes the line.
            (r'\A(\ufeff?)(---)([a-zA-Z][\w-]*)?([ \t]*\n)'
             r'((?:[^\n]*\n)*?)'
             r'(---)([ \t]*)$',
             bygroups(Text, Punctuation, Keyword.Type, Text, Comment.Special,
                      Punctuation, Text)),

            # A comment fence is matched WHOLE - opener, body and closer in
            # one rule - and the one-line comment follows it, because `%%%`
            # also matches the line form.
            #
            # Whole is what makes an UNTERMINATED opener fall through to the
            # line form, which is the rule: an opener with no matching closer
            # ahead "does NOT open a block. The line degrades to a
            # `comment_line`." A separate state cannot decide that - it has
            # already been entered by the time the input runs out
            # (markup-carve/pygments-carve#30). It is also the only shape that
            # can carry the opener's own WIDTH (`%%%%` closes on `%%%%` alone,
            # which is how a comment nests a shorter fence) and its COLUMN
            # (every line up to the closer carries the opener's indent or is
            # blank; a line further left has left the container, so a closer
            # past it belongs to no open fence) into the search for the closer.
            #
            # The `(?!\2)` on the blank alternative is not decoration. Without
            # it both alternatives match a whitespace-only line whenever the
            # opener is at column 0, and an opener with no closer then
            # backtracks exponentially: 22 such lines took 0.8s, and each
            # further line doubles it.
            (r'^((?:\A\ufeff)?)([ \t]*)(%%%+)([^\n]*)(\n)'
             r'((?:\2[^\n]*\n|(?!\2)[ \t]*\n)*?)'
             r'(\2)(\3)(?!%)([^\n]*)',
             bygroups(Text, Text, Comment.Preproc, Comment, Text,
                      Comment, Text, Comment.Preproc, Comment)),
            # The MARGIN IS CAPTURED, like every other block rule's. `bygroups`
            # emits only the groups it is given, so a margin the pattern consumes
            # outside one reaches no token at all and the lexer stops reproducing
            # its input - which it did in 30 corpus documents
            # (markup-carve/pygments-carve#33).
            (r'^(' + _MARGIN + r')(%%)([^\n]*)',
             bygroups(Text, Comment.Preproc, Comment)),

            # A code or raw fence is matched WHOLE - opener, body and closer in
            # one rule - and the lone-fence line follows the pair, because an
            # opener also matches it.
            #
            # WHOLE IS WHAT MAKES THE BODY OPAQUE. A separate state cannot hold
            # it: none of that state's rules matched a bare newline, and
            # Pygments resets the stack to `root` at every line no rule
            # matches, so the state was abandoned before one body character was
            # read and `# x` inside a Python block was scoped as a heading
            # (markup-carve/pygments-carve#32). Whole is also the only shape
            # that can carry the opener's own CHARACTER and WIDTH (`\3\4*`: the
            # grammar's `char(close) = char(open) and len(close) >= len(open)`)
            # and its COLUMN (`\2`, exactly - "a closing run indented PAST its
            # opener is not a delimiter but code content", which is what lets a
            # fence hold a fence as sample text) into the search for the closer.
            #
            # The body alternative is a single one, `[^\n]*\n`, taken lazily.
            # There is exactly one way to split a span into whole lines, so the
            # closer search never backtracks the way a second, overlapping
            # alternative made it (markup-carve/pygments-carve#34).
            #
            # `_FENCE_BODY_LINES` IS THE BOUND ON THAT SEARCH, and it is load
            # bearing. An opener that never finds its closer scans what is left
            # of the document, so a file of openers that cannot pair - `` ```x ``
            # repeated - costs one scan per line and the whole is QUADRATIC.
            # Measured unbounded, doubling the input from 12000 to 96000
            # characters of it multiplied the time by 3.05, 2.89 and 4.46, up to
            # 35.9s; bounded, by 2.54, 2.25 and 2.15, up to 3.5s - which is 3.6x
            # what this lexer costs on 96000 characters of ordinary prose, and
            # the ratio near 2 that carve-grammars' `scan-superlinear.mjs` calls
            # linear.
            #
            # WHAT THE BOUND TRADES AWAY: a fence whose body is longer than
            # `_FENCE_BODY_LINES` does not pair, and its opener degrades to the
            # lone-fence line below. The longest body in the 1564-document spec
            # corpus is 3 lines and the longest across the spec's own
            # documentation is 76.
            #
            # THE OPENER MUST CONFORM BEFORE IT CLAIMS A BODY. `_FENCE_INFO` is
            # the guard: an info string outside the grammar's three shapes is an
            # INVALID-FENCE FALLBACK and opens nothing, so pairing on one would
            # bury a paragraph the corpus renders. It is a lookahead rather than
            # the capture groups themselves, so the groups stay the ones the
            # lone-fence rules below use and the two readings of an opener line
            # cannot drift apart.
            #
            # A raw block's `=FORMAT` routes the payload to that output format
            # verbatim. It is emitted as one token including the `=`, because
            # the format word without its sigil is not the construct. It takes
            # no title and no label, so its guard is the format word alone.
            (r'^((?:\A\ufeff)?)([ \t]*)((`|~)\4{2,})'
             r'(?= ?=[a-zA-Z][\w+.-]*[ \t]*$)'
             r'([ \t]*)(=[a-zA-Z][\w+.-]*)([^\n]*)(\n)'
             r'((?:[^\n]*\n){0,' + str(_FENCE_BODY_LINES) + r'}?)'
             r'(\2)(\3\4*)([ \t]*)$',
             _fenced(6, Text, Text, Punctuation, None, Text, Keyword.Type,
                     using(this, state='infostring'), Text,
                     _BODY, Text, Punctuation, Text)),
            (r'^((?:\A\ufeff)?)([ \t]*)((`|~)\4{2,})'
             r'(?= ?(?:' + _FENCE_INFO + r')?[ \t]*$)'
             r'([ \t]*)([a-zA-Z][\w+#.-]*)?([^\n]*)(\n)'
             r'((?:[^\n]*\n){0,' + str(_FENCE_BODY_LINES) + r'}?)'
             r'(\2)(\3\4*)([ \t]*)$',
             _fenced(6, Text, Text, Punctuation, None, Text, Name.Builtin,
                     using(this, state='infostring'), Text,
                     _BODY, Text, Punctuation, Text)),

            # A FENCE LINE THIS LEXER DOES NOT PAIR: an opener with no matching
            # closer ahead, and the closer of a pair the rules above did not
            # take. It colours the delimiter run and its info string and claims
            # nothing under it.
            #
            # WHAT THAT TRADES AWAY, written down rather than left to be
            # rediscovered: an unterminated fence at document level really does
            # open a code block that runs to the end of what encloses it, and
            # here it does not. The line-based sibling grammars make the same
            # trade for the same reason - inside a container an opener with no
            # closer opens nothing, and a body that ran to end of input there
            # would swallow the container's own closer and every block after
            # it. Burial is the direction that loses a reader's text
            # (markup-carve/pygments-carve#30).
            (r'^(' + _MARGIN + r')(`{3,}|~{3,})([ \t]*)(=[a-zA-Z][\w+.-]*)',
             bygroups(Text, Punctuation, Text, Keyword.Type)),
            (r'^(' + _MARGIN + r')(`{3,}|~{3,})([ \t]*)([a-zA-Z][\w+#.-]*)?([^\n]*)',
             bygroups(Text, Punctuation, Text, Name.Builtin,
                      using(this, state='infostring'))),

            # A fence inside a container: on an item's marker line, or behind a
            # quote marker. `_ContainerFence` walks the body, because neither
            # closer can be found by a pattern.
            (_ITEM_FENCE,
             _fenced(8, Text, Text, Punctuation, Text, Punctuation, None, Text,
                     using(this, state='fencelang'), using(this, state='infostring'),
                     Text, _BODY, Text, Punctuation, Text)),
            (_QUOTED_FENCE,
             _fenced(8, Text, Text, Punctuation, Text, Punctuation, None, Text,
                     using(this, state='fencelang'), using(this, state='infostring'),
                     Text, _QUOTED_BODY, Text, Punctuation,
                     Text, Punctuation, Text)),

            # Container divs. A reserved kind word (note, tip, figure, ...) names
            # a known container; `:::` followed by a sigil is a layout form: `|`
            # a line block, `>` a quote, `\` hard breaks.
            (r'^(' + _MARGIN + r')(:{3,})([ \t]*)([|>\\])', bygroups(Text, Punctuation, Text, Operator)),
            (r'^(' + _MARGIN + r')(:{3,})([ \t]*)([a-zA-Z][\w-]*)?([^\n]*)',
             bygroups(Text, Punctuation, Text, Keyword.Namespace,
                      using(this, state='infostring'))),

            # A caption line attaches to the block above or below it.
            (r'^(' + _MARGIN + r')(\^)([ \t]+)', bygroups(Text, Punctuation, Text), 'caption'),

            # Headings. Carve has no setext form, so a `#` run is the only
            # spelling and a trailing `{...}` is NOT an attribute block here.
            (r'^(' + _MARGIN + r')(#{1,6})([ \t]+)',
             bygroups(Text, Punctuation, Text), 'heading'),

            # Thematic break, before the list rules so `---` is not a bullet.
            (r'^' + _MARGIN + r'(?:\*[ \t]*){3,}$', Punctuation),
            (r'^' + _MARGIN + r'(?:-[ \t]*){3,}$', Punctuation),
            (r'^' + _MARGIN + r'(?:_[ \t]*){3,}$', Punctuation),

            # Definition markers: footnote, link reference, abbreviation. The
            # separator after the colon must START WITH A LITERAL SPACE - a
            # tab-first separator makes the line an ordinary paragraph - and a
            # footnote or abbreviation needs content after it.
            #
            # A leading marker run is part of the shape: a definition is a
            # definition on `- [t]: /t` too, and the corpus resolves the call in
            # those documents. A marker line that instead folds into an open
            # paragraph is over-coloured here, the same way an indented block
            # opener is - telling the two apart needs the container model this
            # lexer deliberately does not carry. The body runs in `defbody`
            # rather than `inline`,
            # because `inline` has no pop rule - `block` includes it, so a pop
            # there would pop the root state - and an unpopped body swallows
            # every block construct in the rest of the document.
            (r'^(' + _MARGIN + r')(' + _MARKER_RUN + r')(\[\^)([^\]\n]+)(\]:)( )(?![ \t]*$)',
             bygroups(Text, using(this, state='markerrun'), Punctuation, Name.Label,
                      Punctuation, Text), 'defbody'),
            # No marker run on the abbreviation form: an abbreviation is defined
            # at document level only, so `- *[HTML]: ...` and `> *[HTML]: ...`
            # are paragraph text (corpus 179, 180).
            (r'^(' + _MARGIN + r')(\*\[)([A-Za-z0-9]+)(\]:)( )(?![ \t]*$)',
             bygroups(Text, Punctuation, Name.Entity, Punctuation, Text), 'defbody'),
            # A link reference definition only where the line COMPLETES the
            # production: a title and an attribute block each behind exactly one
            # space, then only trailing spaces or tabs, so `[a]: /u zzz` and
            # `[a]: /u  "T"` are paragraphs (CARVE-P3-005). A label may not
            # start with `@` (CARVE-P3-003).
            (r'^(' + _MARGIN + r')(' + _MARKER_RUN + r')(\[)(?!@)([^\]\n]+)(\]:)'
             r'( [' + _LINE_SPACE + r']*)([^' + _WHITE_SPACE + r']+)'
             r'(?:( )(?:("(?:\\"|[^"\n])*")|(\'(?:\\\'|[^\'\n])*\')))?'
             r'(?:( )(' + _ATTRS_UNCHECKED + r'))?([ \t]*)$',
             bygroups(Text, using(this, state='markerrun'), Punctuation, Name.Label,
                      Punctuation, Text, Name.Tag, Text, String.Double, String.Single,
                      Text, Name.Attribute, Text)),

            # A definition-list term. Its `:` descriptions are scoped only in
            # the `deflist` state it opens, so a `:` line with no term above it
            # stays a paragraph.
            (r'^(' + _MARGIN + r')(::)( +[ \t]*)(?=[^ \t\n])',
             bygroups(Text, Punctuation, Text), ('deflist', 'termtail', 'heading')),

            # `- > +`: a list item opening a quote whose first block is a `+`.
            (r'^(' + _MARGIN + r')((?:> )*)((?:(?:[-*](?:' + _ATTRS + r')?(?: \[[ xX_>?-]\])?|(?:'
             + _ORDINAL + r'[.)]|\.)(?:' + _ATTRS + r')?) )+)((?:> )+)(\+)([ \t]*)$', _hosted_quote_plus),
            # A `+` alone behind quote prefixes is read by its column. Each `>`
            # needs a space after it: `>+`, `>>+` and `>> +` are paragraph text.
            (r'^(' + _MARGIN + r')((?:> [ \t]*)+)(\+)([ \t]*)$', _quoted_plus),
            # Blockquote marker. A marker must be followed by a space or end the
            # line; `>foo`, `>\tq` and `>> q` are paragraphs. A block after the marker is lexed as
            # one (`_NESTED_TAIL`), as it is after a list marker below.
            (r'^(' + _MARGIN + r')(>)(?= |$)' + _NESTED_TAIL,
             bygroups(Text, Punctuation, Text, using(this, state='nested')), 'quoteline'),

            # Task items before plain bullets, so the state marker is its own
            # token. Only a bullet takes one, and only the `task_state` set.
            (r'^(' + _MARGIN + r')((?:[-*] +)*[-*](?:' + _ATTRS + r')?)'
             r'( +)(\[[ xX_>?-]\])(?= +[ \t]*[^ \t\n])'
             r'(?:( +)(\+)(?=[ \t]*$))?',
             bygroups(Text, Punctuation, Text, Name.Constant, Text, Operator)),

            (r'^(' + _MARGIN + r')((?:[-*] +)*[-*](?:' + _ATTRS + r')?)( +)(\+)([ \t]*)$',
             bygroups(Text, Punctuation, Text, Operator, Text)),
            (r'^(' + _MARGIN + r')(' + _ORDINAL + r'[.)](?:' + _ATTRS + r')?|\.(?:' + _ATTRS + r')?)( +)(\+)([ \t]*)$',
             bygroups(Text, Number.Integer, Text, Operator, Text)),

            # Bullets. A run of markers on one line opens nested lists at once
            # (`- - A`), and attributes may be glued straight onto the marker.
            # `+` is not a bullet: `+ foo` is a paragraph. Every list marker
            # needs a space and then content.
            (r'^(' + _MARGIN + r')((?:[-*] +)*[-*](?:' + _ATTRS + r')?)(?= +[ \t]*[^ \t\n])'
             + _NESTED_TAIL,
             bygroups(Text, Punctuation, Text, using(this, state='nested'))),
            # A lone `+` is a marker only at an open container's marker column.
            (r'^(' + _MARGIN + r')(\+)([ \t]*)$', _continuation_marker),

            # Ordered markers: numeric, alphabetic, roman, and the bare `.` that
            # continues the enclosing sequence. Any of them may carry glued
            # attributes.
            (r'^(' + _MARGIN + r')(' + _ORDINAL + r'[.)](?:' + _ATTRS + r')?)(?= +[ \t]*[^ \t\n])'
             + _NESTED_TAIL,
             bygroups(Text, Number.Integer, Text, using(this, state='nested'))),
            (r'^(' + _MARGIN + r')(\.(?:' + _ATTRS + r')?)(?= +[ \t]*[^ \t\n])' + _NESTED_TAIL,
             bygroups(Text, Number.Integer, Text, using(this, state='nested'))),

            # Tables. The header marker, the alignment run and the separator row
            # are their own tokens; cell content is lexed inline.
            # A `continuation_row` ends in `|`; without one the line is prose.
            (r'^(' + _MARGIN + r')(\+)(?=[^\n]*\|[ \t]*$)([^\n]*)', _continuation_row),
            # A row ends in `|`, or in `|` and a glued row attribute block:
            # `| a | b` with no closing pipe is a paragraph.
            (r'^(' + _MARGIN + r')(\|=[<>^v~]*)(?=' + _ROW_END + r')',
             bygroups(Text, Operator), 'tablerow'),
            (r'^(' + _MARGIN + r')(\|)(?=' + _ROW_END + r')',
             bygroups(Text, Punctuation), 'tablerow'),

            # A standalone attribute block, which may span lines.
            (r'^(' + _MARGIN + r')(' + _ATTRS_LINE + r')', bygroups(Text, Name.Attribute)),

            # A paragraph. Its later lines are not tried as list items or
            # captions, which do not interrupt one: the engine renders `para`,
            # `- x`, `1. y` and `^ z` on consecutive lines as one paragraph.
            (_PARAGRAPH_START, _silent, 'paragraph'),

            include('inline'),
        ],

        # An open paragraph, to a blank line or a line that interrupts it. Its
        # lines are inline only; a line that interrupts pops back to `block`,
        # which reads it.
        'paragraph': [
            (r'\n' + _PARAGRAPH_BREAK, Text, '#pop'),
            include('inline'),
        ],

        # Inside a definition list, from its first term to a blank line that
        # no `:` or `::` line follows, or to a line that opens another block.
        'deflist': [
            (r'^(?=' + _MARGIN + _OTHER_OPENER + r')', Text, '#pop'),
            (r'^[ \t]*\n(?![ \t]*(?:\n|::? ))', Text, '#pop'),
            (r'^(' + _MARGIN + r')(::)( +[ \t]*)(?=[^ \t\n])',
             bygroups(Text, Punctuation, Text), ('termtail', 'heading')),
            (_DESCRIPTION_FENCE,
             _fenced(8, Text, Text, Punctuation, Text, Punctuation, None, Text,
                     using(this, state='fencelang'), using(this, state='infostring'),
                     Text, _BODY, Text, Punctuation, Text)),
            (r'^(' + _MARGIN + r')(:)(?= +[ \t]*[^ \t\n])' + _NESTED_TAIL, _description_marker),
            include('block'),
        ],

        # The lines a term continues onto. A lone `+` or a `+ a |` line here is
        # the term's text, not a continuation marker or row: the engine renders
        # `:: t`, `+` as the term `t +`.
        'termtail': [
            (r'^(?=[ \t]*(?:\n|\Z)|' + _MARGIN + r'(?:::? |' + _OTHER_OPENER + r'|' + _INTERRUPTER + r'))',
             Text, '#pop'),
            (r'\n', Text),
            include('inline'),
        ],

        # A fence body, reached only through the whole-fence rules above, which
        # hand it the text BETWEEN the delimiters. Nothing in it is Carve - the
        # one exception is the code-callout marker, which the spec puts inside
        # a fence on purpose (`callout marker in fence` in the shared construct
        # inventory).
        #
        # It is not a pushed state and cannot be one: a body spans lines, and a
        # pushed state is abandoned at the first newline no rule matches. Here
        # `[^<]+` matches a newline like any other character, which is also
        # what makes the body reproduce its input.
        'fencebody': [
            (r'<\d+>', Name.Constant),
            (r'[^<]+|<', String.Backtick),
        ],

        # The body of a fence behind a quote marker: each line's marker, then
        # the line verbatim, as `fencebody` reads it.
        'quotedfencebody': [
            (r'^[ \t]*>+[ \t]?', Punctuation),
            (r'<\d+>', Name.Constant),
            (r'[^<\n]+|<|\n', String.Backtick),
        ],

        # The language slot of a container fence, which may also be a raw
        # block's `=FORMAT`.
        'fencelang': [
            (r'=[a-zA-Z][\w+.-]*', Keyword.Type),
            (r'[^\n]+', Name.Builtin),
        ],

        # The remainder of a fence or container opener line: a quoted title, a
        # bracketed label, and an attribute block.
        'infostring': [
            (r'"[^"\n]*"', String.Double),
            (r'\[[^\]\n]*\]', Name.Label),
            (_ATTRS, Name.Attribute),
            (r'[^\n]', Text),
        ],

        'heading': [
            (r'$', Text, '#pop'),
            include('lineverbatim'),
            include('inlinecontent'),
            (_plain_run(), Generic.Heading),
            (r'[^\n]', Generic.Heading),
        ],

        'quoteline': [
            (r'$', Text, '#pop'),
            include('lineverbatim'),
            include('inlinecontent'),
            (_plain_run(), Generic.Emph),
            (r'[^\n]', Generic.Emph),
        ],

        'caption': [
            (r'$', Text, '#pop'),
            include('lineverbatim'),
            include('inlinecontent'),
            (_plain_run(), Generic.Subheading),
            (r'[^\n]', Generic.Subheading),
        ],

        'tablerow': [
            (r'$', Text, '#pop'),
            # A header cell marker, optionally carrying an alignment run. The
            # pipe is part of it, so `|=` reads as one construct.
            (r'\|=[<>^v~]*', Operator),
            # A separator row cell, in the native and the GFM spelling.
            (r'(?<=\|)[ \t]*:?-{2,}:?[ \t]*(?=\|)', Punctuation),
            (r'(?<=\|)[ \t]*[<>^v~]{1,2}[ \t]*(?=\|)', Operator),
            (r'\|', Punctuation),
            include('inlinecontent'),
            # An unclosed code run in a row stops at the row's closing pipe.
            (r'(?<!`)(`+)(?!`)([^\n]*?)(?=\|(?:' + _ATTRS + r')?[ \t]*$)',
             bygroups(Punctuation, String.Backtick)),
            (_plain_run(r'|'), Text),
            (r'[^\n|]', Text),
        ],

        'nested': [
            (r'^\+(?=[ \t]*$)', Punctuation),
            include('block'),
        ],

        # The marker run a definition line may carry, tokenized the way the
        # marker rules in `block` tokenize the same markers on their own.
        'markerrun': [
            (_ORDINAL + r'[.)](?:' + _ATTRS + r')?', Number.Integer),
            (r'\.(?:' + _ATTRS + r')?', Number.Integer),
            (r'[-*](?:' + _ATTRS + r')?', Punctuation),
            (r'>+', Punctuation),
            (r'[ \t]+', Text),
        ],

        # A definition's body: inline content that ends with its line.
        'defbody': [
            (r'$', Text, '#pop'),
            (r'(?<=\]: )\+(?=[ \t]*$)', _definition_plus),
            include('inline'),
        ],

        # ------------------------------------------------------------------
        # Inline level
        # ------------------------------------------------------------------
        'inline': [
            include('inlinecontent'),
            include('opencode'),
            # Content as runs rather than one token per character. A run starts
            # at content, so a line's margin still reaches `.` a character at a
            # time, and the block rules that take a margin whole stay the only
            # readers that do.
            (r'(?![ \t])' + _plain_run(), Text),
            (r'\n', Text),
            (r'.', Text),
        ],

        'opencode': [
            # A code span in a paragraph closes on a later line of it, and a
            # run with no partner runs to the paragraph's end: the engine reads
            # `x `a` `b` as two spans, the second to the end. The one-line
            # forms in `inlinecontent` come first and keep their own families.
            (_Code(r'(!)(`+)(?!`)', r'([\s\S]*?)(\2)?', reach='paragraph', unclosed=True),
             bygroups(Operator, Punctuation, Literal, Punctuation)),
            (_Code(r'(\$\$?)(`+)(?!`)', r'([\s\S]*?)(\2)?', reach='paragraph', unclosed=True),
             bygroups(Operator, Punctuation, String.Other, Punctuation)),
            (_Code(r'(?<!`)(`+)(?!`)', r'([\s\S]*?)(\1)?', reach='paragraph', unclosed=True),
             bygroups(Punctuation, String.Backtick, Punctuation)),
        ],

        # The content of an emphasis span, lexed as inline content of its own,
        # so a span inside a span is scoped: `{=a *b* c=}` marks a strong.
        'strong': [
            include('inlinecontent'),
            include('opencode'),
            (_plain_run() + r'|[^\n]|\n', Generic.Strong),
        ],
        'emph': [
            include('inlinecontent'),
            include('opencode'),
            (_plain_run() + r'|[^\n]|\n', Generic.Emph),
        ],
        'underline': [
            include('inlinecontent'),
            include('opencode'),
            (_plain_run() + r'|[^\n]|\n', Generic.Underline),
        ],
        'deleted': [
            include('inlinecontent'),
            include('opencode'),
            (_plain_run() + r'|[^\n]|\n', Generic.Deleted),
        ],
        'inserted': [
            include('inlinecontent'),
            include('opencode'),
            (_plain_run() + r'|[^\n]|\n', Generic.Inserted),
        ],

        # A link's label, brackets included: link text is inline content, so
        # `[a *b*](u)` holds a strong. A reference link's label stays whole:
        # whether it resolves is not known here, and the engine renders an
        # unresolved one, `[*b*][]`, as literal text.
        'linklabel': [
            include('inlinecontent'),
            (_plain_run() + r'|[^\n]|\n', Name.Entity),
        ],

        # The content of a braced span: the same, except that its own
        # delimiter is literal there. The engine renders `{*a *b* c*}` as one
        # strong holding `a *b* c`, and `{=a *b* c=}` as a mark holding a strong.
        'forcedstrong': [(r'\*', Generic.Strong), include('strong')],
        'forcedemph': [(r'/', Generic.Emph), include('emph')],
        'forcedunderline': [(r'_', Generic.Underline), include('underline')],
        'forceddeleted': [(r'~', Generic.Deleted), include('deleted')],
        'forcedinserted': [(r'=', Generic.Inserted), include('inserted')],

        'lineverbatim': [
            (r'(!)(`+)(?!`)((?:(?!(?<!`)\2(?!`))[^\n])*)((?<!`)\2(?!`)|$)',
             bygroups(Operator, Punctuation, Literal, Punctuation)),
            (r'(\$\$?)(`+)(?!`)((?:(?!(?<!`)\2(?!`))[^\n])*)((?<!`)\2(?!`)|$)',
             bygroups(Operator, Punctuation, String.Other, Punctuation)),
            (r'(`+)(?!`)((?:(?!(?<!`)\1(?!`))[^\n])*)((?<!`)\1(?!`)|$)',
             bygroups(Punctuation, String.Backtick, Punctuation)),
        ],

        'inlinecontent': [
            # An escape wins over every delimiter that follows it. A backslash
            # at END OF LINE escapes nothing - it is a hard break, and needs its
            # own rule because the general form requires a following character.
            (r'\\(?=\n|$)', String.Escape),
            (r'\\[!-/:-@\[-`{-~]', String.Escape),

            # A trailing comment runs to end of line from anywhere on it.
            (r'(%%)([^\n]*)$', bygroups(Comment.Preproc, Comment)),

            # Verbatim families first: nothing inside them is markup. A span
            # opens on a whole backtick run and closes on the next run of
            # exactly its width, so `x `a``b` y` holds `a``b`. The literal form is a `!` PREFIX on a code span, not a trailing
            # attribute, and it has to be tried before plain inline code or the
            # `!` would be read as text and the span as ordinary code.
            (_Code(r'(!)(`+)(?!`)', r'([^\n]*?)(\2)'),
             bygroups(Operator, Punctuation, Literal, Punctuation)),
            (_Code(r'(\$\$)(`+)(?!`)', r'([^\n]*?)(\2)'),
             bygroups(Operator, Punctuation, String.Other, Punctuation)),
            (_Code(r'(\$)(`+)(?!`)', r'([^\n]*?)(\2)'),
             bygroups(Operator, Punctuation, String.Other, Punctuation)),
            (_Code(r'(?<!`)(`+)(?!`)', r'([^\n]*?)(\1)'), bygroups(Punctuation, String.Backtick, Punctuation)),

            # The reserved include directive `{{ path #section @key:value }}`
            # (PART 9 section 19, grammar.ebnf `include_directive`). The core
            # leaves it literal; a processor expands it only when a host
            # supplies a resolver.
            #
            # One directive rule, because its own selector is spelled with constructs
            # this lexer already knows: `#section` is the tag rule below and an
            # option slot is the mention rule, so without this `#intro` came out
            # coloured as a hashtag inside a path. After the verbatim family, so
            # a directive in a code span stays literal; before every other brace
            # rule, none of which can spell `{{`.
            # The selector names an EXPLICIT id, so its first character may be
            # an ASCII digit (`id_attribute` -> `explicit_identifier`), and the
            # whitespace run before a part is OPTIONAL in every position: the
            # path stops at `#` and `@` on its own, so `{{ c.crv#intro }}` and
            # `{{ c.crv@shift:1 }}` are well formed.
            #
            # The tail is spelled so that one text has ONE reading: the part
            # glued to the path starts with `#` or `@` (or follows a quoted
            # path), and every later part is behind a required run. With the
            # run optional, `(?:[ \t]*[^\s}]+)*` split a word 2^n ways, and
            # `{{ chapter-one.crv#introduction` with no closer took 166s.
            (_Scan(r'(\{\{)([ \t]+)((?:"(?:\\.|[^"\\])*"|[^#@}\s"][^#@}\s]*))',
                   r'((?:(?<=")[^\s}]+|[#@][^\s}]*)?(?:[ \t]+[^\s}]+)*)([ \t]+)(\}\})',
                   r'\}\}', stop=True),
             bygroups(Punctuation, Text, Name.Namespace, using(this, state='includeparts'), Text, Punctuation)),

            # CriticMarkup substitution and comment, before the forced family:
            # `{~old~>new~}` also matches the forced-strike shape.
            (_Scan(r'(\{~)' + _WHOLE, r'([\s\S]*?)(~>)([\s\S]*?)(~\})', (r'~>', r'~\}'), masked='critic', reach='block'),
             bygroups(Punctuation, using(this, state='deleted'), Operator, using(this, state='inserted'),
                      Punctuation)),
            (_Scan(r'(\{#)' + _WHOLE, r'([^\n]*?)(#\})', r'#\}'), bygroups(Punctuation, Comment, Punctuation)),

            # The braced FORCED emphasis family. Braces make a delimiter apply
            # where the bare form would not - `my{_path_}name` is underline
            # inside a word - so the content is emphasis and the braces are its
            # delimiters, not an attribute block.
            (_Braced(r'(\{\*)' + _WHOLE, r'([\s\S]+?)(\*\})'), bygroups(Punctuation, using(this, state='forcedstrong'), Punctuation)),
            (_Braced(r'(\{/)' + _WHOLE, r'([\s\S]+?)(/\})'), bygroups(Punctuation, using(this, state='forcedemph'), Punctuation)),
            (_Braced(r'(\{_)' + _WHOLE, r'([\s\S]+?)(_\})'), bygroups(Punctuation, using(this, state='forcedunderline'), Punctuation)),
            (_Braced(r'(\{~)' + _WHOLE, r'([\s\S]+?)(~\})'), bygroups(Punctuation, using(this, state='forceddeleted'), Punctuation)),

            # Braced inline families. Sup and sub are braced-only in Carve: a
            # bare `^x^` or `,x,` is literal text.
            (_Braced(r'(\{\^)' + _WHOLE, r'([\s\S]+?)(\^\})'), bygroups(Punctuation, using(this, state='emph'), Punctuation)),
            (_Braced(r'(\{,)' + _WHOLE, r'([\s\S]+?)(,\})'), bygroups(Punctuation, using(this, state='emph'), Punctuation)),
            (_Braced(r'(\{=)' + _WHOLE, r'([\s\S]+?)(=\})'), bygroups(Punctuation, using(this, state='forcedinserted'), Punctuation)),
            (_Braced(r'(\{\+)' + _WHOLE, r'([\s\S]+?)(\+\})'), bygroups(Punctuation, using(this, state='inserted'), Punctuation)),
            # The braced en dash. A deletion needs content, so `{--}` is never
            # one, and `{--}x-}` is a dash followed by text, not a deletion.
            (r'\{--\}', Punctuation),
            (_Braced(r'(\{-)' + _WHOLE, r'([\s\S]+?)(-\})'), bygroups(Punctuation, using(this, state='deleted'), Punctuation)),
            (_Scan(r'(\{%)' + _WHOLE, r'([\s\S]*?)(%\})', r'%\}', reach='block'), bygroups(Comment.Preproc, Comment, Comment.Preproc)),

            # An inline footnote carries content; a reference carries a label.
            # Each opens only where a `]` lies ahead in its paragraph: an unclosed
            # `^[` or `:name[` is text, and as a pushed state it swallowed every
            # block after it, since only a `]` popped it.
            (_Scan(r'\^\[', '', r'\]', reach='paragraph', whole=False),
             Punctuation, 'inlinefootnote'),
            (_FOOTNOTE_REF, bygroups(Punctuation, Name.Label, Punctuation)),

            # A citation before a link: both open with `[`, and `[@key]` or
            # `[+@key]` would otherwise be read as a link label.
            (_CITATION, bygroups(Punctuation, Name.Variable, Punctuation)),

            # Image, then link, then a bare span. All three share the `[...]`
            # shape and differ only in the prefix and what follows.
            (_IMAGE,
             bygroups(String.Other, Punctuation, Name.Tag, Punctuation)),
            (_IMAGE_REF, bygroups(String.Other, Name.Label)),
            (_LINK,
             bygroups(using(this, state='linklabel'), Punctuation, Name.Tag, Punctuation)),
            (_LINK_REF, bygroups(Name.Entity, Name.Label)),
            (_LINK_ATTRS, using(this, state='linklabel')),

            # A cross-reference to a heading id.
            (_CROSS_REFERENCE, bygroups(Punctuation, Name.Namespace, Punctuation)),
            # An autolink.
            (_AUTOLINK,
             bygroups(Punctuation, Name.Tag, Punctuation)),

            # The `:name[...]` extension form.
            (_Scan(r'(:)([a-zA-Z][\w-]*)(\[)', '', r'\]', reach='paragraph', whole=False),
             bygroups(Punctuation, Name.Function, Punctuation), 'rolebody'),

            # A symbol shortcode, whose name may start with a sign, as in `:+1:`.
            # A code callout marker is scoped only inside a fence: outside one
            # the engine renders `<1>` as text.
            (r'(?<![\w:]):[\w+-]+:(?![\w:])', Name.Constant),

            # An attribute block attached to the construct before it.
            (_ATTRS, Name.Attribute),

            # Bare emphasis delimiters, each carrying the word-boundary guards
            # the grammar states for it. "No bare delimiter emphasizes
            # intraword; the forced `{X ... X}` family is the deliberate
            # intraword escape hatch", and the guards are what say so:
            #
            #     bare_opener(d) = <!(alnum | '_' | d | slash_if(d)), d, !(ws | d)
            #     bare_closer(d) = <&(non_ws), d, !(alnum)
            #
            # spelled here as `(?<![\w<d>])` before the opener, `(?!<d>)` after
            # it, and `(?![^\W_])` after the closer - `\w` being alnum and `_`
            # together, and `[^\W_]` alnum alone, because a `_` AFTER a closer
            # is allowed and one BEFORE an opener is not. The two inner
            # non-space boundaries were already there, in the `\S` at each end
            # of the content.
            #
            # `slash_if(d)` adds `/` to the opener's lookbehind for `/` and `_`
            # only - path protection, `/a/_b_` and `snake_/case/` - which for
            # `/` coincides with same-delimiter adjacency. `*`, `~` and `=` are
            # NOT guarded against a preceding `/`, so `a/~y~` is a strike.
            #
            # WITHOUT THEM ANY NON-SPACE RUN BETWEEN TWO DELIMITERS WAS
            # EMPHASIS, wherever it sat: 16 corpus documents carried a run the
            # lexer scoped whose delimiters SURVIVE into the expected HTML,
            # which is the corpus saying no span was opened there. The clearest
            # was a document whose own sentence is the assertion - "Dates like
            # 1/2/2024 stay literal" - with `/2/` scoped as emphasis
            # (markup-carve/pygments-carve#36).
            #
            # The combined `/*` opener is guarded on its OUTER `/`, which is
            # where the grammar puts it: "the boundary guards apply to the
            # OUTER `/`; the inner `*` is part of the two-char token". A space
            # after the opener or before the closer leaves an italic holding
            # literal asterisks: `a /* b */ c` is `<em>* b *</em>`.
            (_Scan(r'(?<![\w/])(/\*)(?!\s)' + _WHOLE, r'([\s\S]+?)(?<!\s)(\*/)(?![^\W_])' + _WHOLE,
                   r'(?<!\s)\*/(?![^\W_])' + _WHOLE, least=1, masked='bare', reach='block'),
             bygroups(Punctuation, using(this, state='strong'), Punctuation)),
            (_Scan(r'(?<![\w*])(\*/)' + _WHOLE, r'([\s\S]+?)(/\*)(?![^\W_])' + _WHOLE, r'/\*(?![^\W_])' + _WHOLE,
                   least=1, masked='bare', reach='block'),
             bygroups(Punctuation, using(this, state='strong'), Punctuation)),
            (_Scan(r'(?<![\w*])(\*)(?!\*)' + _WHOLE, r'(\S(?:[\s\S]*?\S)?)(\*)(?![^\W_])' + _WHOLE,
                   r'(?<=\S)\*(?![^\W_])' + _WHOLE, least=1, masked='bare', reach='block'),
             bygroups(Punctuation, using(this, state='strong'), Punctuation)),
            (_Scan(r'(?<![\w/])(/)(?!/)' + _WHOLE, r'(\S(?:[\s\S]*?\S)?)(/)(?![^\W_])' + _WHOLE,
                   r'(?<=\S)/(?![^\W_])' + _WHOLE, least=1, masked='bare', reach='block'),
             bygroups(Punctuation, using(this, state='emph'), Punctuation)),
            (_Scan(r'(?<![\w/])(_)(?!_)' + _WHOLE, r'(\S(?:[\s\S]*?\S)?)(_)(?![^\W_])' + _WHOLE,
                   r'(?<=\S)_(?![^\W_])' + _WHOLE, least=1, masked='bare', reach='block'),
             bygroups(Punctuation, using(this, state='underline'), Punctuation)),
            (_Scan(r'(?<![\w~])(~)(?!~)' + _WHOLE, r'(\S(?:[\s\S]*?\S)?)(~)(?![^\W_])' + _WHOLE,
                   r'(?<=\S)~(?![^\W_])' + _WHOLE, least=1, masked='bare', reach='block'),
             bygroups(Punctuation, using(this, state='deleted'), Punctuation)),
            # A bare `=` carrying a comparison or an arrow tail on its left is
            # not a highlight delimiter: PART 9's inline precedence excepts "a
            # delimiter that begins a multi-char smart-typography pattern ...
            # the pattern is consumed first". `< > !` is every character the
            # language puts in front of a `=` to make one.
            #
            # BOTH ends are guarded, one more than Prism, whose closer is
            # unguarded. The engine guards both: `x =y z<= w` renders
            # `x =y z≤ w`, no mark at all. Nothing is guarded on the RIGHT,
            # also from the engine - `=>` is not an arrow any more, so
            # `a =foo=> b` marks `foo` and `a =>foo= b` marks `>foo`.
            (_Scan(r'(?<![\w=<>!])(=)(?!=)' + _WHOLE, r'(\S(?:[\s\S]*?\S)?)(?<![<>!])(=)(?![^\W_])' + _WHOLE,
                   r'(?<=\S)(?<![<>!])=(?![^\W_])' + _WHOLE, least=1, masked='bare', reach='block'),
             bygroups(Punctuation, using(this, state='inserted'), Punctuation)),

            # A mention and a tag, each one token: the sigil is part of the name
            # rather than punctuation beside it.
            (r'(?<![\w/])@[\w][\w.-]*', Name.Variable.Magic),
            (r'(?<![\w&])\#[\w][\w-]*', Name.Variable.Instance),

            # Smart typography: the spec grammar's `arrow`, `comparison` and
            # `typographic_symbol` plus the dash and ellipsis runs. Nineteen
            # alternatives, the set Prism and highlight.js carry.
            #
            # Longest first, or a shorter alternative that prefixes a longer one
            # wins: `<->` before `<-`, `<==` before `<=`. `<==>` is deliberately
            # NOT one of them - it is `<==` and then a literal `>`, rendering
            # `⇐>`, and matching it whole was an over-colour.
            (r'<-->|<--|-->|<=>|<==|==>|<->|<-|->|!=|<=|>=', Operator),
            (r'(?<!-)---(?!-)|(?<!-)--(?!-)', Punctuation),
            (r'\.\.\.', Punctuation),
            # `(c) (r) (tm) +-` render fixed characters, the same kind of thing
            # the `:name:` shortcode above produces, so they share its type.
            # Lowercase only: `(C)` and `(TM)` stay literal.
            (r'\(c\)|\(r\)|\(tm\)|\+-', Name.Constant),
        ],

        # The tail of a directive: selector, option slots, and whatever else was
        # written there. Scoped BY PART - the outer rule is what keeps the tag
        # and mention rules out, so painting one token buys nothing, and a
        # reader wants the path to look like a path.
        #
        # A part that is neither a section nor an option stays plain text rather
        # than being refused, matching the processor, which leaves a malformed
        # directive alone.
        'includeparts': [
            (r'[ \t]+', Text),
            (r'#[A-Za-z0-9_][A-Za-z0-9_-]*', Name.Label),
            (r'(@[A-Za-z_][A-Za-z0-9_-]*)(:)([^\s}]+)',
             bygroups(Name.Variable, Punctuation, Literal)),
            (r'[^\s}]+', Text),
        ],

        'inlinefootnote': [
            (r'\]', Punctuation, '#pop'),
            (r'\n' + _PARAGRAPH_BREAK, Text, '#pop'),
            include('inlinecontent'),
            (_plain_run(r'\]'), Generic.Emph),
            (r'[^\]\n]', Generic.Emph),
            (r'\n', Text),
        ],

        'rolebody': [
            (r'\]', Punctuation, '#pop'),
            (r'\n' + _PARAGRAPH_BREAK, Text, '#pop'),
            include('inlinecontent'),
            (_plain_run(r'\]'), Name.Function),
            (r'[^\]\n]', Name.Function),
            (r'\n', Text),
        ],
    }
