#!/usr/bin/env python3
"""Turn a Carve document's frontmatter into a JSON object of keys.

Usage: meta.py <input.crv> [block.json]

<block.json> is the frontmatter block as the engine parsed it,
`{"format": ..., "content": ...}` or `null`, written by `render.php --meta` /
`render.mjs --meta`. The engine decides what counts as frontmatter, so the
opener rules live in one place. Without it (or when it cannot be read) the
block is found here with the same opener rules: `---`, then one space and a
format, a format right after the dashes, or only trailing whitespace.

`json` content is parsed as JSON. Anything else is read loosely as `key: value`
lines (`key = value` for toml): quotes are removed, `[a, b]` and `- item`
lists become arrays, and a ` # comment` after a value is dropped.
"""
import json
import re
import sys
from pathlib import Path

if len(sys.argv) not in (2, 3):
    sys.exit("usage: meta.py <input.crv> [block.json]")

OPENER = re.compile(r"\A---(?: ?(?P<fmt>[A-Za-z][\w.+-]*))?[ \t]*\r?\n")
CLOSER = re.compile(r"^---[ \t]*$", re.MULTILINE)


def find_block(src: str):
    m = OPENER.match(src)
    if not m:
        return None
    end = CLOSER.search(src, m.end())
    if not end:
        return None
    return {"format": m.group("fmt") or "yaml", "content": src[m.end():end.start()].rstrip("\r\n")}


def engine_block(path: str):
    try:
        raw = Path(path).read_text(encoding="utf-8").strip()
        return json.loads(raw) if raw else False
    except (OSError, ValueError):
        return False


def scalar(val: str):
    """Unquote and drop a trailing comment from one value."""
    val = val.strip()
    if val[:1] in "\"'":
        close = val.find(val[0], 1)
        if close != -1 and (close == len(val) - 1 or re.match(r"\s+#", val[close + 1:])):
            return val[1:close]
    val = re.sub(r"(^|\s+)#.*$", "", val).strip()
    if val.startswith("[") and val.endswith("]"):
        return [scalar(s) for s in val[1:-1].split(",") if s.strip()]
    return val


def parse_lines(content: str, sep: str) -> dict:
    out = {}
    key_line = re.compile(r"^([A-Za-z0-9_-]+)\s*" + re.escape(sep) + r"\s*(.*)$")
    last = None
    for line in content.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        item = re.match(r"^\s+-\s+(.*)$", line)
        if item and last is not None:
            if not isinstance(out[last], list):
                out[last] = []
            out[last].append(scalar(item.group(1)))
            continue
        kv = key_line.match(line)
        if not kv:
            last = None
            continue
        last = kv.group(1)
        out[last] = scalar(kv.group(2))
    return out


def parse(block) -> dict:
    if not isinstance(block, dict) or not isinstance(block.get("content"), str):
        return {}
    fmt = str(block.get("format") or "yaml").lower()
    if fmt == "json":
        try:
            data = json.loads(block["content"])
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}
    return parse_lines(block["content"], "=" if fmt == "toml" else ":")


src = Path(sys.argv[1]).read_text(encoding="utf-8")
block = engine_block(sys.argv[2]) if len(sys.argv) == 3 else False
if block is False:
    block = find_block(src)
print(json.dumps(parse(block), ensure_ascii=False))
