#!/usr/bin/env bash
#
# Fence gate: every named fence carries a visible language label that sits
# clear of the code, Blade is highlighted, a fence name an older Pygments lacks
# falls back to its nearest lexer, and an unknown language is labeled but left
# unhighlighted.
#
# The browser half skips cleanly when Chrome or websocket-client is absent.
set -uo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
LIB="$HERE/lib"
FIX="$HERE/tests/fixtures/fences.crv"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

pass=0; fail=0; skip=0
ok()   { echo "  ok   - $1"; pass=$((pass+1)); }
bad()  { echo "  FAIL - $1"; fail=$((fail+1)); }
skipd(){ echo "  skip - $1"; skip=$((skip+1)); }
has()  { if grep -qF -- "$3" "$2"; then ok "$1"; else bad "$1 (missing: $3)"; fi; }
hasnt(){ if grep -qF -- "$3" "$2"; then bad "$1 (unexpected: $3)"; else ok "$1"; fi; }

have_chrome() {
  [ -n "${CHROME_BIN:-}" ] && command -v "$CHROME_BIN" >/dev/null 2>&1 && return 0
  command -v google-chrome >/dev/null 2>&1 || command -v chromium >/dev/null 2>&1 \
    || command -v chromium-browser >/dev/null 2>&1
}

html="$WORK/fences.html"
echo "== fences: emitted HTML =="
if ! "$HERE/crv2pdf.sh" "$FIX" "$html" --html >/dev/null 2>&1; then
  bad "could not render the fixture to HTML"
  echo "fences: passed $pass, failed $fail, skipped $skip"
  exit 1
fi
has   "blade fence is labeled"            "$html" 'data-lang="blade"'
has   "php fence is labeled"              "$html" 'data-lang="php"'
has   "unknown language is still labeled" "$html" 'data-lang="csv"'
hasnt "a text fence gets no label"        "$html" 'data-lang="text"'
if python3 -c 'import pygments' 2>/dev/null; then
  has   "blade is highlighted"            "$html" 'language-blade syntax-highlighted'
  has   "blade directive is a keyword"    "$html" '<span class="tok-k">@carve</span>'
  has   "blade comment is a comment"      "$html" '<span class="tok-cm">{{-- BLADECOMMENT --}}</span>'
  hasnt "an e-mail address is no directive" "$html" '<span class="tok-k">@example</span>'
  has   "yml falls back to the YAML lexer" "$html" 'language-yml syntax-highlighted'
  hasnt "an unknown language stays unhighlighted" "$html" 'language-csv syntax-highlighted'
  # Classes a lexer emits that the theme left unstyled print as plain ink.
  for cls in tok-gi tok-gd tok-gp tok-nb; do
    has "$cls is styled" "$WORK/fences.html" ".syntax-highlighted .$cls"
  done
  has   "diff marks its added line"       "$html" '<span class="tok-gi">+added</span>'
  has   "{.diff} block is presented"      "$html" '<pre class="diff has-diff" data-lang="js">'
  has   "{.diff} removed line is marked"  "$html" '<span class="line diff remove"><span class="diff-marker">-</span>'
  has   "{.diff} added line is marked"    "$html" '<span class="line diff add"><span class="diff-marker">+</span>'
  # The marker is stripped before highlighting, so `+ x.remove(` lexes as JS.
  has   "{.diff} line body is highlighted" "$html" '<span class="diff-marker">+</span><span class="tok-w"> </span><span class="tok-nx">fileIcon</span>'
  # The diff body lexes as one block, so `<?php` on line 1 still makes line 3 PHP.
  has   "{.diff} keeps lexer state across lines" "$html" '<span class="diff-marker">+</span><span class="tok-k">echo</span>'
  # A marker-only first line must not shift the markers onto the wrong code.
  has   "{.diff} leading marker-only line keeps alignment" "$html" '<span class="line diff remove"><span class="diff-marker">-</span><span class="tok-nx">old</span>'
  # Nor may a marker-only LAST line cost the block its highlighting.
  has   "{.diff} trailing marker-only line keeps highlighting" "$html" '<span class="diff-marker">+</span><span class="tok-kd">const</span>'
  # A PHP snippet with no opening tag is PHP, not HTML text.
  has   "php snippet without <?php is highlighted" "$html" '<span class="tok-nv">$converter</span>'
  # One that opens with the tag keeps it as one delimiter.
  has   "php with an opening tag keeps it whole" "$html" '<span class="tok-cp">&lt;?php</span>'
  # Fence names Pygments has no alias for borrow the lexer that reads them cleanly.
  has   "tsx closes its JSX tag"          "$html" '<span class="tok-p">}&lt;/</span><span class="tok-nt">p</span>'
  has   "json5 bare key is a name"        "$html" '<span class="tok-nx">json5key</span>'
  has   "jsonl is highlighted as JSON"    "$html" '<span class="tok-nt">&quot;jsonlkey&quot;</span>'
  has   "vb is highlighted as VB.NET"     "$html" '<span class="tok-k">Dim</span>'
  # Callout markers are taken out before highlighting and put back on their line.
  has   "a callout survives highlighting"  "$html" '<span class="tok-p">):</span>  <b class="callout" data-callout="1">1</b>'
  has   "a last-line callout survives"     "$html" '<b class="callout" data-callout="2">2</b></code></pre>'
  has   "a {.diff} callout stays in its row" "$html" '<b class="callout" data-callout="3">3</b></span></code></pre>'
  # A marker alone on the last line must not cost the fence its other markers.
  has   "a marker-only last line keeps the earlier callout" "$html" '<span class="tok-w">  </span><b class="callout" data-callout="4">4</b>'
  has   "a marker-only last line keeps its own callout" "$html" '<b class="callout" data-callout="5">5</b></code></pre>'
  # A quoted `(` in directive arguments must not leave the lexer inside them.
  has   "blade quoted paren closes its directive" "$html" '<span class="tok-k">@endif</span>'
else
  skipd "no Pygments - highlighting is UNMEASURED"
fi

echo "== fences: rendered page (computed style) =="
if ! have_chrome; then
  skipd "no Chrome binary - label drawing is UNMEASURED"
elif ! python3 -c 'import websocket' 2>/dev/null; then
  skipd "no websocket-client - label drawing is UNMEASURED"
elif ! python3 "$LIB/probe_cdp.py" "$html" "$HERE/tests/fences.js" > "$WORK/probe.json" 2>"$WORK/probe.err"; then
  bad "probe_cdp.py failed: $(tr -d '\n' < "$WORK/probe.err" | cut -c1-200)"
else
  python3 - "$WORK/probe.json" > "$WORK/verdicts" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding='utf-8'))
out = []
def v(ok, name): out.append(("ok" if ok else "FAIL") + "\t" + name)

v(len(d["fences"]) == 19, f"19 fences in the DOM (saw {len(d['fences'])})")
for r in d["diffRows"]:
    v(r["background"] not in ("rgba(0, 0, 0, 0)", "transparent"), f"diff {r['kind']} row is tinted ({r['background']})")
    v(abs(r["width"] - r["preWidth"]) <= 2, f"diff {r['kind']} row spans the block ({r['width']:.0f} of {r['preWidth']:.0f}px)")
v(len(d["diffRows"]) == 10, f"10 tinted diff rows (saw {len(d['diffRows'])})")
for p in d["fences"]:
    if p["lang"] is None:
        v(p["content"] in ("none", "normal"), f"unlabeled fence draws no label (content {p['content']})")
        continue
    at = f"{p['lang']} fence"
    v(p["content"] == f'"{p["lang"]}"', f"{at}: label drawn as {p['content']}")
    top = p["firstLineTop"]
    v(top is not None and p["labelBottom"] <= top,
      f"{at}: label ends above the first code line ({p['labelBottom']:.1f} <= {top})")
print("\n".join(out))
PY
  while IFS=$'\t' read -r verdict name; do
    [ -n "${name:-}" ] || continue
    if [ "$verdict" = "ok" ]; then ok "$name"; else bad "$name"; fi
  done < "$WORK/verdicts"
fi

echo "fences: passed $pass, failed $fail, skipped $skip"
[ "$fail" -eq 0 ]
