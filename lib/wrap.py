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
</style></head><body>
{header}
{fragment}
{byline}
</body></html>
"""

out_path.write_text(doc, encoding="utf-8")
print(f"wrote {out_path}")
