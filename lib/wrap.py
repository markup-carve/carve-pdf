#!/usr/bin/env python3
"""Assemble a print-ready HTML document from a Carve HTML fragment + metadata.

Usage: wrap.py <fragment.html> <meta.json> <base_dir> <out.html> <css...>

<meta.json> is the frontmatter as JSON (produced by `render.php --meta`).
<base_dir> is the source .crv's directory; emitted as <base href> so relative
image/link URLs in the document resolve against it.
Recognized keys: title, description, author, date, kicker, tags, lang.
Any CSS files given are inlined into a single <style> block.
"""
import html
import json
import re
import sys
from pathlib import Path

# assets.py owns where the optional client libraries live, so `make check`
# reports on the same paths the renderer reads rather than its own copy of them.
import assets

if len(sys.argv) < 5:
    sys.exit("usage: wrap.py <fragment.html> <meta.json> <base_dir> <out.html> <css...>")

frag_path, meta_path, base_dir, out_path = map(Path, sys.argv[1:5])
css_paths = [Path(p) for p in sys.argv[5:]]
base_href = base_dir.resolve().as_uri().rstrip("/") + "/"

fragment = frag_path.read_text(encoding="utf-8")
# Reveal all disclosure widgets (details + spoilers) in print - there is no
# click to open a PDF. Adds `open` to any <details> that lacks it.
fragment = re.sub(r"<details(?![^>]*\bopen\b)", "<details open", fragment)


# Fence names an older Pygments does not know, mapped to the nearest lexer it
# has. Only consulted when the name itself fails, so a native lexer wins.
LEXER_FALLBACKS = {
    "yml": "yaml",
    "jsonc": "json",
    "json5": "javascript",
    "jsonl": "json",
    "tsx": "jsx",
    "vb": "vbnet",
    "env": "bash",
    "dotenv": "bash",
    "svg": "xml",
    "patch": "diff",
    "vue": "html",
    "svelte": "html",
    "astro": "html",
    "latte": "html",
    "hbs": "handlebars",
    "mustache": "handlebars",
    "gql": "graphql",
    "neon": "yaml",
}

# Fence names that say "no language"; they get no label.
UNLABELED_FENCES = {"", "text", "txt", "plain", "plaintext", "none", "mermaid", "chart"}

FENCE_BLOCK = re.compile(r"<pre(?P<pre>[^>]*)><code(?P<code>[^>]*)>(?P<body>.*?)</code></pre>", re.DOTALL)


def fence_language(code_attrs: str) -> str:
    classes = re.search(r'class="([^"]*)"', code_attrs)
    if not classes:
        return ""
    return next((name[9:] for name in classes.group(1).split() if name.startswith("language-")), "")


def label_fences(fragment_html: str) -> str:
    """Carry each fence's language onto its <pre> as `data-lang` for the label."""

    def replace(match):
        pre_attrs = match.group("pre")
        language = fence_language(match.group("code"))
        if language.lower() in UNLABELED_FENCES or "data-lang=" in pre_attrs:
            return match.group(0)
        label = html.escape(language, quote=True)
        return f'<pre{pre_attrs} data-lang="{label}"><code{match.group("code")}>{match.group("body")}</code></pre>'

    return FENCE_BLOCK.sub(replace, fragment_html)


DIFF_MARKER = re.compile(r"^[+\- ]")


def pre_classes(pre_attrs: str) -> list:
    found = re.search(r'class="([^"]*)"', pre_attrs)
    return found.group(1).split() if found else []


def with_class(attrs: str, name: str) -> str:
    found = re.search(r'class="([^"]*)"', attrs)
    if not found:
        return f'{attrs} class="{name}"'
    names = found.group(1).split()
    if name not in names:
        names.append(name)
    return attrs[:found.start(1)] + " ".join(names) + attrs[found.end(1):]


def render_diff(source: str, highlight_block) -> str:
    """Per-line `{.diff}` presentation, the shape of carve-grammars' renderLanguageDiff.

    The marker-stripped lines are highlighted as ONE block so a comment, string
    or `<?php` opened on one line still colors the next; Pygments closes and
    reopens its spans at every newline, so the result splits back into lines.
    """
    lines = source[:-1].split("\n") if source.endswith("\n") else source.split("\n")
    markers = [line[0] if DIFF_MARKER.match(line) else "" for line in lines]
    bodies = [line[1:] if marker else line for line, marker in zip(lines, markers)]
    rendered = highlight_block("\n".join(bodies)).split("\n")
    if len(rendered) != len(lines):
        # A marker on the wrong line is worse than no color.
        rendered = [html.escape(body) for body in bodies]
    out = []
    for marker, body in zip(markers, rendered):
        line_class = {"+": "line diff add", "-": "line diff remove"}.get(marker, "line")
        marker_span = f'<span class="diff-marker">{html.escape(marker)}</span>' if marker else ""
        out.append(f'<span class="{line_class}">{marker_span}{body}</span>')
    return "\n".join(out)


# A code callout is the engine's only markup inside a fence body, always last on its line.
CALLOUT = re.compile(r'<b class="callout" data-callout="\d+">\d+</b>[ \t]*$')


def split_callouts(body: str):
    """Fence body without its callout markers, and the marker for each line."""
    lines = body.split("\n")
    markers = [m.group(0).rstrip() if (m := CALLOUT.search(line)) else "" for line in lines]
    plain = [CALLOUT.sub("", line) if marker else line for line, marker in zip(lines, markers)]
    return "\n".join(plain), markers


def restore_callouts(rendered: str, markers: list, is_diff: bool) -> str:
    lines = rendered.split("\n")
    while len(markers) > len(lines) and not markers[-1]:
        markers = markers[:-1]
    # Highlighting drops trailing empty lines, and a marker-only line is one once
    # its marker is out; nothing else can be missing, so the slots come back empty.
    lines += [""] * (len(markers) - len(lines))
    if len(lines) != len(markers):
        return rendered
    out = []
    for line, marker in zip(lines, markers):
        if marker and is_diff and line.endswith("</span>"):
            line = line[:-len("</span>")] + marker + "</span>"
        elif marker:
            line += marker
        out.append(line)
    return "\n".join(out)


def highlight_code(fragment_html: str) -> str:
    """Highlight named fences statically so HTML and PDF need no client JS.

    A `{.diff}` fence is highlighted line by line with its marker stripped, as
    the carve-grammars diff helper does, so `- old()` tokenizes as `old()`.
    """
    try:
        from pygments import highlight
        from pygments.formatters import HtmlFormatter
        from pygments.lexers import get_lexer_by_name
        from pygments.util import ClassNotFound
        from carve_lexer import CarveLexer
        from blade_lexer import BladeLexer
    except ImportError:
        if re.search(r'<code[^>]*class="[^"]*language-', fragment_html):
            sys.stderr.write("wrap.py: Pygments not found; leaving code fences unhighlighted\n")
        highlight = None

    def lexer_for(language: str, source: str):
        name = language.lower()
        if highlight is None or not name or name in ("mermaid", "chart"):
            return None
        # stripnl=False keeps leading blank lines, which a `{.diff}` pairs with markers.
        if name in ("carve", "crv"):
            return CarveLexer(stripnl=False)
        if name == "blade":
            return BladeLexer(stripnl=False)
        # Pygments reads PHP only after an opening tag; a snippet without one
        # would come out as unhighlighted HTML text.
        options = {"startinline": True} if name == "php" and "<?" not in source else {}
        try:
            return get_lexer_by_name(name, stripnl=False, **options)
        except ClassNotFound:
            try:
                return get_lexer_by_name(LEXER_FALLBACKS[name], stripnl=False)
            except (ClassNotFound, KeyError):
                return None

    def replace(match):
        pre_attrs, code_attrs = match.group("pre"), match.group("code")
        body, callouts = split_callouts(match.group("body"))
        source = html.unescape(body)
        lexer = lexer_for(fence_language(code_attrs), source)
        is_diff = "diff" in pre_classes(pre_attrs)
        if lexer is None and not is_diff:
            return match.group(0)
        if lexer is None:
            highlight_block = html.escape
        else:
            formatter = HtmlFormatter(nowrap=True, classprefix="tok-")
            code_attrs = with_class(code_attrs, "syntax-highlighted")

            def highlight_block(text):
                # Pygments appends a newline only when one is missing, so add it
                # ourselves and strip exactly that one: a trailing blank line in
                # the source keeps its place.
                return highlight(text + "\n", lexer, formatter)[:-1]

        if is_diff:
            pre_attrs = with_class(pre_attrs, "has-diff")
            rendered = render_diff(source, highlight_block)
        else:
            rendered = highlight_block(source).rstrip("\n")
        if any(callouts):
            rendered = restore_callouts(rendered, callouts, is_diff)
        return f"<pre{pre_attrs}><code{code_attrs}>{rendered}</code></pre>"

    return FENCE_BLOCK.sub(replace, fragment_html)


# carve-php emits a ```math fence as bare TeX in a <pre>; KaTeX's auto-render
# skips <pre> and needs the display delimiters, both of which carve-js writes.
MATH_FENCE = re.compile(
    r'<pre(?P<attrs>[^>]*\bclass="(?=[^"]*\bmath\b)(?=[^"]*\bdisplay\b)[^"]*"[^>]*)>(?!\s*\\\[)(?P<tex>.*?)</pre>',
    re.DOTALL,
)
fragment = MATH_FENCE.sub(lambda m: f'<div{m.group("attrs")}>\\[{m.group("tex")}\\]</div>', fragment)
fragment = label_fences(highlight_code(fragment))
try:
    meta = json.loads(meta_path.read_text(encoding="utf-8") or "{}")
except Exception:
    meta = {}
css = "\n".join(p.read_text(encoding="utf-8") for p in css_paths if p.is_file())


def esc(v) -> str:
    return html.escape(str(v), quote=True)


# --- page geometry + break-control overrides (from frontmatter) -------------
# Frontmatter can come from untrusted documents, so paper/margin are strictly
# validated before being inlined into a <style> block (else a crafted value
# could break out of @page and inject arbitrary CSS / remote resource loads).
_PAPER_NAMED = re.compile(
    r"^(a[0-9]|b[0-9]|c[0-9]|letter|legal|ledger|tabloid)"
    r"(\s+(portrait|landscape))?$",
    re.IGNORECASE,
)
_DIMS = re.compile(r"^\d+(\.\d+)?(mm|cm|in|pt|pc|px)(\s+\d+(\.\d+)?(mm|cm|in|pt|pc|px))?$", re.IGNORECASE)
_MARGIN = re.compile(r"^(\d+(\.\d+)?(mm|cm|in|pt|pc|px)\s*){1,4}$", re.IGNORECASE)


def _valid(value, *patterns):
    v = str(value).strip()
    return v if any(p.match(v) for p in patterns) else None


overrides = []
paper = _valid(meta.get("paper", ""), _PAPER_NAMED, _DIMS) if meta.get("paper") else None
margin = _valid(meta.get("margin", ""), _MARGIN) if meta.get("margin") else None
if meta.get("paper") and not paper:
    sys.stderr.write(f"wrap.py: ignoring invalid `paper` frontmatter: {meta.get('paper')!r}\n")
if meta.get("margin") and not margin:
    sys.stderr.write(f"wrap.py: ignoring invalid `margin` frontmatter: {meta.get('margin')!r}\n")
if paper or margin:
    decls = ""
    if paper:
        decls += f" size: {paper};"
    if margin:
        decls += f" margin: {margin};"
    overrides.append(f"@page {{{decls} }}")
page_breaks = str(meta.get("pageBreaks", "h2"))
if page_breaks in ("none", "manual"):
    overrides.append("h2 { break-before: auto; }")
    overrides.append(
        "hr:has(+ section > h2:first-child),"
        " section:has(+ section > h2:first-child) > hr:last-child { display: block; }"
    )
if overrides:
    css += "\n/* frontmatter overrides */\n" + "\n".join(overrides) + "\n"


# --- optional client-side renderers (math / diagrams / charts) --------------
# KaTeX, Mermaid, and Chart.js all run in Chrome before printToPDF. They share a
# single window.__carveReady promise that print_cdp awaits, so multiple
# renderers in one document all complete before the PDF is captured. Each is
# only wired in when (a) the document uses it and (b) its library is found.
# A library the document asks for and we cannot supply is reported. Letting it
# degrade in silence is how a PDF quietly loses its math.
def _library(env_name, feature, package, kind):
    found, ignored = assets.resolve(env_name, package, kind)
    if ignored is not None:
        sys.stderr.write(
            f"wrap.py: ignoring ${env_name}={ignored!r}: not found there, trying the defaults\n"
        )
    if found is None:
        sys.stderr.write(
            f"wrap.py: {feature} left unrendered: no {package} found. "
            f"Install it (npm install {package}) or point ${env_name} at it.\n"
        )
    return found


def client_assets():
    head_parts, lib_scripts, init_steps = [], [], []

    # KaTeX (math) - synchronous render
    if 'class="math' in fragment:
        root = _library("CARVE_KATEX", "math", "katex", "dir")
        if root:
            fonts_uri = (root / "fonts").resolve().as_uri()
            kcss = (root / "katex.min.css").read_text(encoding="utf-8").replace(
                "url(fonts/", f"url({fonts_uri}/"
            )
            head_parts.append(f"<style>{kcss}</style>")
            lib_scripts.append(f"<script>{(root / 'katex.min.js').read_text(encoding='utf-8')}</script>")
            lib_scripts.append(f"<script>{(root / 'contrib' / 'auto-render.min.js').read_text(encoding='utf-8')}</script>")
            init_steps.append(
                "renderMathInElement(document.body,{delimiters:["
                "{left:'\\\\[',right:'\\\\]',display:true},"
                "{left:'\\\\(',right:'\\\\)',display:false}],throwOnError:false});"
            )

    # Mermaid (diagrams) - async render to SVG
    if re.search(r'class="[^"]*\bmermaid\b', fragment):
        src = _library("CARVE_MERMAID", "mermaid diagrams", "mermaid", "file")
        if src:
            lib_scripts.append(f"<script>{src.read_text(encoding='utf-8')}</script>")
            init_steps.append(
                "document.querySelectorAll('pre.mermaid').forEach(function(el){el.textContent=el.textContent;});"
                # Mermaid draws at 16px in its own font; a diagram reads as part of the
                # page at the body's size and family, and layout follows the font.
                "if(window.mermaid){var bf=getComputedStyle(document.body).fontFamily;"
                "mermaid.initialize({startOnLoad:false,fontFamily:bf,fontSize:13,"
                "themeVariables:{fontSize:'13px',fontFamily:bf},"
                # Sequence boxes and gaps are sized for 16px text; scale them with it.
                "sequence:{width:120,height:46,actorMargin:40,messageMargin:32,boxMargin:8}});"
                "await mermaid.run({querySelector:'pre.mermaid'});}"
            )

    # Chart.js (charts) - JSON config -> canvas
    if re.search(r'class="[^"]*\bchart\b', fragment):
        src = _library("CARVE_CHART", "charts", "chart.js", "file")
        if src:
            lib_scripts.append(f"<script>{src.read_text(encoding='utf-8')}</script>")
            init_steps.append(
                "document.querySelectorAll('pre.chart').forEach(function(el){"
                "var cfg;try{cfg=JSON.parse(el.textContent);}catch(e){return;}"
                "cfg.options=Object.assign({},cfg.options||{});"
                "cfg.options.responsive=false;cfg.options.animation=false;"
                "var cv=document.createElement('canvas');cv.width=680;cv.height=360;"
                "cv.style.cssText='display:block;margin:0 auto 14px;max-width:100%';"
                "el.replaceWith(cv);if(window.Chart)new Chart(cv.getContext('2d'),cfg);});"
                "await new Promise(function(r){requestAnimationFrame(function(){requestAnimationFrame(r);});});"
            )

    if not (head_parts or lib_scripts or init_steps):
        return "", ""
    body = "".join(lib_scripts)
    if init_steps:
        body += (
            "<script>window.__carveReady=(async()=>{"
            + "".join(init_steps)
            + "})().catch(function(e){console.error(e);});</script>"
        )
    return "".join(head_parts), body


client_head, client_body = client_assets()


title = meta.get("title") or "Carve document"

# kicker: explicit key, else uppercased tags, else nothing
kicker = meta.get("kicker")
if not kicker:
    tags = meta.get("tags")
    if isinstance(tags, list) and tags:
        kicker = " · ".join(t.upper() for t in tags[:4])
    elif isinstance(tags, str) and tags:
        kicker = tags.upper()

header = ""
if kicker:
    header = f'<header class="doc-header"><p class="kicker">{esc(kicker)}</p></header>'

# byline footer from author / date
byline_bits = []
if meta.get("author"):
    byline_bits.append("By " + esc(meta["author"]))
if meta.get("date"):
    byline_bits.append(esc(meta["date"]))
byline = ""
if byline_bits:
    byline = f'<p class="doc-byline">{" · ".join(byline_bits)}</p>'

doc = f"""<!doctype html>
<html lang="{esc(meta.get('lang', 'en'))}"><head><meta charset="utf-8">
<base href="{esc(base_href)}">
<title>{esc(title)}</title>
<style>
{css}
</style>
{client_head}
</head><body class="carve">
{header}
{fragment}
{byline}
{client_body}
</body></html>
"""

out_path.write_text(doc, encoding="utf-8")
print(f"wrote {out_path}")
