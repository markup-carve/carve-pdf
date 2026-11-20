"""Carve 0.2 rules built on the shared token scanner.

Vendored from markup-carve/pygments-carve commit 12843183ed7cc2293294cdf6eb55ca651588945d (MIT) for offline PDF rendering.
"""

import re
from types import FunctionType

from pygments.lexer import bygroups
from pygments.token import Comment, Generic, Punctuation, String, Text

import carve_scanner as old
from carve_scanner import CsvLexer, TsvLexer  # noqa: F401  (0.1 import path)


class CommentFenceScan2(old._CommentFenceScan):
    """End only on a full closer line of at least the opener's width."""

    def end(self, text, opened):
        line = opened.start(2)
        depth = old._fence_depth(opened.group(3))
        base = old._line_prefix(text, line, opened.start(5))[2]
        column = old._column(text, line, opened.start(5))
        if self.scan.own_line:
            owner, verse = old._owner_column(text, line, column, depth, base)
            if verse and column - owner > 3:
                return None
            column = owner
        elif opened.group(4).startswith('[^'):
            column = old._column(text, line, opened.start(4)) + 2
        else:
            last = None
            for last in old._LIST_MARKER.finditer(opened.group(3)):
                pass
            if last and last.group(1) and not opened.group(3)[last.end():].strip():
                column = old._column(text, line, opened.start(3) + last.end(1) - 3)
        closer = re.compile(r'(?:[ \t]*> ){0,%d}[ \t]*%%{%d,}[ \t]*$'
                            % (depth, len(opened.group(5))))
        at = opened.end()
        if not opened.group(7):
            return self._held(text, line, at)
        while at < len(text):
            stop = text.find('\n', at)
            stop = len(text) if stop == -1 else stop
            if closer.match(text, at, stop):
                return self._held(text, line, stop)
            found, width, _, indent = old._line_prefix(text, at, stop)
            if not text.startswith('%%', at + width):
                if found < depth or (at + width < stop and indent < column):
                    return self._held(text, line, at)
            at = stop + 1
        return self._held(text, line, len(text))


class CommentFence2(old._CommentFence):
    def matcher(self, flags):
        return CommentFenceScan2(self, flags)


def comment_fence2(lexer, match):
    """Use the 0.2 wider closer when assigning delimiter tokens."""
    def closer(depth, width):
        return re.compile(r'(?:[ \t]*> ){0,%d}[ \t]*%%{%d,}[ \t]*(?=\n|$)'
                          % (depth, width))

    emitter = FunctionType(old._comment_fence.__code__,
                           {**old._comment_fence.__globals__, '_comment_closer': closer})
    tokens = list(emitter(lexer, match))
    closer_line = match.string.rfind('\n', 0, match.end(8)) + 1
    for offset, token, value in tokens:
        if (token is Comment and offset >= closer_line
                and re.fullmatch(r'%+', value)):
            yield offset, Comment.Preproc, value
        else:
            yield offset, token, value


def changed(rule, pattern):
    """Keep a rule's action and state transitions while changing its shape."""
    return (pattern, *rule[1:])


def code_only(pattern):
    return pattern.replace('`{3,}|~{3,}', '`{3,}').replace('(`|~)', '(`)')


rules = {state: list(entries) for state, entries in old._BaseCarveLexer.tokens.items()}
block = rules['block']

for state, indices in [('block', (1, 19)), ('deflist', (5,))]:
    for index in indices:
        original = old._BaseCarveLexer.tokens[state][index]
        scan = original[0]
        rules[state][index] = (CommentFence2(scan.opener, own_line=scan.own_line),
                               comment_fence2, *original[2:])

# Region markers are structural lines. A regular comment remains skipped.
region = (r'^(' + old._MARGIN + r')(%%[ \t]*#(?:region[ \t]+[A-Za-z_][\w-]*'
          r'|endregion(?:[ \t]+[A-Za-z_][\w-]*)?))([ \t]*)$',
          bygroups(Text, Comment.Special, Text))
block.insert(2, region)

for index in (3, 4):
    rule = old._BaseCarveLexer.tokens['block'][index]
    pattern = code_only(rule[0].pattern)
    if index == 3:
        pattern = pattern.replace(r'[\w+.-]*[ \t]*$)',
                                  r'[\w+.-]*(?: +"[^"\n]*")?[ \t]*$)')
    block[block.index(rule)] = changed(rule, old._AttachedFence(pattern))
for index in (5, 6):
    rule = old._BaseCarveLexer.tokens['block'][index]
    block[block.index(rule)] = changed(rule, code_only(rule[0]))
for index in (7, 8):
    rule = old._BaseCarveLexer.tokens['block'][index]
    scan = rule[0]
    opener = code_only(scan.opener)
    rest = code_only(scan.pattern[len(scan.opener):])
    block[block.index(rule)] = changed(rule, old._ContainerFence(opener, rest, quoted=scan.quoted))

# Quote and line-block fence labels use a quoted title in 0.2.
block.insert(block.index(old._BaseCarveLexer.tokens['block'][9]),
             (r'^(' + old._MARGIN + r')(:{3,})([ \t]*)([|>\\])( +)("[^"\n]*")',
              bygroups(Text, Punctuation, Text, old.Operator, Text, String.Double)))

heading = old._BaseCarveLexer.tokens['block'][12]
block[block.index(heading)] = changed(
    heading, r'^(' + old._MARGIN + r')((?:#{1,6}|={1,6}))( )(?=[^ \t\n])')
break_rule = old._BaseCarveLexer.tokens['block'][13]
block[block.index(break_rule)] = changed(break_rule, r'^' + old._MARGIN + r'\*{3,}[ \t]*$')
caption = old._BaseCarveLexer.tokens['block'][11]
block[block.index(caption)] = changed(caption, r'^(?<!\n\n)(' + old._MARGIN + r')(\^)([ \t]+)')

# A one-line attribute block can wait for the next block. A wrapped one is text.
attribute = old._BaseCarveLexer.tokens['block'][34]
attribute_at = block.index(attribute)
block[attribute_at] = changed(
    attribute, old._AttrsLine(r'^(' + old._MARGIN + r')(' + old._ATTRS
                               + r')(?=[ \t]*\n(?![ \t]*\n)[ \t]*\S)'))
block.insert(attribute_at + 1,
             (r'^' + old._MARGIN + old._ATTRS + r'(?=[ \t]*(?:\n[ \t]*\n|\Z))', Text))

# A header mark is still structural. Glued alignment marks and GFM separator
# rows are ordinary cell content in 0.2.
header = old._BaseCarveLexer.tokens['block'][32]
block[block.index(header)] = changed(header, r'^(' + old._MARGIN + r')(\|=)()(?=' + old._ROW_END + r')')
cell = old._BaseCarveLexer.tokens['block'][33]
block[block.index(cell)] = changed(cell, r'^(' + old._MARGIN + r')(\|)()(?=' + old._ROW_END + r')')

# The marker with a plus sign no longer attaches a following block. The table
# continuation row remains, since it is a separate 0.2 table production.
removed_block = {14, 15, 21, 22, 25, 26, 28}
for index in sorted(removed_block, reverse=True):
    block.remove(old._BaseCarveLexer.tokens['block'][index])

ordered2 = (r'(?:\d{1,9}[.)]|(?:[A-Za-z]|[ivxlcdm]+|[IVXLCDM]+)'
            r'(?:\)|\.(?=(?:' + old._ATTRS + r')? )))')
for index in (23, 24, 27, 29, 30):
    rule = old._BaseCarveLexer.tokens['block'][index]
    if rule in block:
        pattern = code_only(rule[0]).replace(old._ORDERED, ordered2)
        block[block.index(rule)] = changed(rule, pattern)

# Only fences, rows, star breaks, valid region lines and blank lines interrupt
# a plain paragraph. Heading, quote and attribute lines are lazy text.
interrupt = (r'(?=[ \t]*(?:\n|\Z)|[ \t]*(?:`{3,}|:{3,}|%{3,}'
             r'|\|(?=[^\n]*\|[ \t]*$)|\*{3,}[ \t]*$'
             r'|%%[ \t]*#(?:region[ \t]+[A-Za-z_][\w-]*'
             r'|endregion(?:[ \t]+[A-Za-z_][\w-]*)?)[ \t]*$))')
rules['paragraph'][0] = changed(rules['paragraph'][0], r'\n' + interrupt)

table = rules['tablerow']
for index in (1, 7, 10, 11):
    table.remove(old._BaseCarveLexer.tokens['tablerow'][index])

inline = rules['inlinecontent']
for index in (8, 35, 36, 39, 40, 41):
    inline.remove(old._BaseCarveLexer.tokens['inlinecontent'][index])

rules['nested'].pop(0)

# A term accepts plain following lines until its description or a blank line.
rules['termtail'].insert(-1, (r'^[^\n]+', Generic.Subheading))

# Subsequent caret lines are text of the first caption, not fresh captions.
rules['caption'][0] = changed(
    rules['caption'][0], r'$(?!\n[ \t]*\^[ \t])')
rules['caption'].insert(1, (r'\n[ \t]*\^[ \t]', Generic.Subheading.Caption))


class CarveLexer(old._BaseCarveLexer):
    """Lexer for Carve 0.2 source."""

    name = 'Carve 0.2'
    aliases = ['carve', 'crv']
    filenames = ['*.crv', '*.carve']
    mimetypes = ['text/x-carve']
    tokens = rules
