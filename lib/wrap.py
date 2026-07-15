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
import os
import re
import sys
from pathlib import Path

if len(sys.argv) < 5:
    sys.exit("usage: wrap.py <fragment.html> <meta.json> <base_dir> <out.html> <css...>")

frag_path, meta_path, base_dir, out_path = map(Path, sys.argv[1:5])
css_paths = [Path(p) for p in sys.argv[5:]]
base_href = base_dir.resolve().as_uri().rstrip("/") + "/"

fragment = frag_path.read_text(encoding="utf-8")
# Reveal all disclosure widgets (details + spoilers) in print - there is no
# click to open a PDF. Adds `open` to any <details> that lacks it.
fragment = re.sub(r"<details(?![^>]*\bopen\b)", "<details open", fragment)
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
if overrides:
    css += "\n/* frontmatter overrides */\n" + "\n".join(overrides) + "\n"


# --- optional KaTeX (only when the document contains math) ------------------
def katex_assets():
    if 'class="math' not in fragment:
        return "", ""
    root = os.environ.get("CARVE_KATEX") or next(
        (d for d in (
            "/media/mark/data/work/git/markup-carve-carve/node_modules/katex/dist",
            "/media/mark/data/work/git/carve-js/node_modules/katex/dist",
        ) if Path(d, "katex.min.css").is_file()),
        None,
    )
    if not root:
        return "", ""  # no KaTeX available -> raw TeX (still readable)
    root = Path(root)
    fonts_uri = (root / "fonts").resolve().as_uri()
    kcss = root.joinpath("katex.min.css").read_text(encoding="utf-8").replace(
        "url(fonts/", f"url({fonts_uri}/"
    )
    kjs = root.joinpath("katex.min.js").read_text(encoding="utf-8")
    autorender = root.joinpath("contrib", "auto-render.min.js").read_text(encoding="utf-8")
    head = f"<style>{kcss}</style>"
    body = (
        f"<script>{kjs}</script><script>{autorender}</script>"
        "<script>renderMathInElement(document.body,{delimiters:["
        '{left:"\\\\[",right:"\\\\]",display:true},'
        '{left:"\\\\(",right:"\\\\)",display:false}],throwOnError:false});</script>'
    )
    return head, body


katex_head, katex_body = katex_assets()


# --- optional Mermaid (only when the document contains diagrams) ------------
def mermaid_body():
    # match `mermaid` as a class token (may sit alongside authored classes)
    if not re.search(r'class="[^"]*\bmermaid\b', fragment):
        return ""
    src = os.environ.get("CARVE_MERMAID") or next(
        (p for p in (
            "/media/mark/data/work/git/vscode-carve/media/mermaid.min.js",
            "/media/mark/data/work/git/carve-js/node_modules/mermaid/dist/mermaid.min.js",
        ) if Path(p).is_file()),
        None,
    )
    if not src:
        return ""  # no mermaid lib -> the source stays visible in a <pre>
    mjs = Path(src).read_text(encoding="utf-8")
    # Unwrap the inner <code>, render to SVG, and expose a promise print_cdp awaits.
    return (
        f"<script>{mjs}</script>"
        "<script>window.__carveReady=(async()=>{"
        "document.querySelectorAll('pre.mermaid').forEach(function(el){el.textContent=el.textContent;});"
        "if(window.mermaid){mermaid.initialize({startOnLoad:false});"
        "await mermaid.run({querySelector:'pre.mermaid'});}"
        "})();</script>"
    )


mermaid_body_html = mermaid_body()


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
{katex_head}
</head><body>
{header}
{fragment}
{byline}
{katex_body}
{mermaid_body_html}
</body></html>
"""

out_path.write_text(doc, encoding="utf-8")
print(f"wrote {out_path}")
