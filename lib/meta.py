#!/usr/bin/env python3
"""Parse a Carve document's leading frontmatter block to JSON (renderer-agnostic).

Usage: meta.py <input.crv>   # prints a JSON object of frontmatter keys

Recognizes the `---<format>\\n ... \\n---` block. Values are parsed loosely:
quoted strings unquoted, `[a, b]` lists into arrays, everything else kept as-is.
"""
import json
import re
import sys
from pathlib import Path

if len(sys.argv) != 2:
    sys.exit("usage: meta.py <input.crv>")

src = Path(sys.argv[1]).read_text(encoding="utf-8")

out = {}
m = re.match(r"^---[a-z]*\r?\n(.*?)\r?\n---\s*\r?\n", src, re.DOTALL)
if m:
    for line in m.group(1).splitlines():
        kv = re.match(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$", line)
        if not kv:
            continue
        key, val = kv.group(1), kv.group(2).strip()
        if len(val) >= 2 and val[0] in "\"'" and val[-1] == val[0]:
            val = val[1:-1]
        elif val.startswith("[") and val.endswith("]"):
            val = [s.strip() for s in val[1:-1].split(",") if s.strip()]
        out[key] = val

print(json.dumps(out, ensure_ascii=False))
