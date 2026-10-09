#!/usr/bin/env bash
#
# Print-style gate: the constructs a visual audit found broken on paper stay
# fixed. Each value is resolved by a browser, because each defect was one rule
# undoing another across the vendored carve-css and this repository's themes.
#
# Skips cleanly when Chrome or websocket-client is absent, and says so.
set -uo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
LIB="$HERE/lib"
FIX="$HERE/tests/fixtures/print-styles.crv"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

pass=0; fail=0; skip=0
ok()   { echo "  ok   - $1"; pass=$((pass+1)); }
bad()  { echo "  FAIL - $1"; fail=$((fail+1)); }
skipd(){ echo "  skip - $1"; skip=$((skip+1)); }

have_chrome() {
  [ -n "${CHROME_BIN:-}" ] && command -v "$CHROME_BIN" >/dev/null 2>&1 && return 0
  command -v google-chrome >/dev/null 2>&1 || command -v chromium >/dev/null 2>&1 \
    || command -v chromium-browser >/dev/null 2>&1
}

echo "== print styles: rendered page (computed style) =="
if ! have_chrome; then
  skipd "no Chrome binary - print styles are UNMEASURED"
elif ! python3 -c 'import websocket' 2>/dev/null; then
  skipd "no websocket-client - print styles are UNMEASURED"
else
  html="$WORK/print-styles.html"
  if ! "$HERE/crv2pdf.sh" "$FIX" "$html" --html >/dev/null 2>&1; then
    bad "could not render the fixture to HTML"
  elif ! python3 "$LIB/probe_cdp.py" "$html" "$HERE/tests/print-styles.js" > "$WORK/probe.json" 2>"$WORK/probe.err"; then
    bad "probe_cdp.py failed: $(tr -d '\n' < "$WORK/probe.err" | cut -c1-200)"
  else
    python3 - "$WORK/probe.json" > "$WORK/verdicts" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding='utf-8'))
out = []
def v(ok, name): out.append(("ok" if ok else "FAIL") + "\t" + name)

body_hrs = [h for h in d["hrs"] if not h["inEndnotes"] and not h["beforePageBreak"]]
note_hrs = [h for h in d["hrs"] if h["inEndnotes"]]
page_hrs = [h for h in d["hrs"] if h["beforePageBreak"]]
v(page_hrs and all(h["display"] == "none" for h in page_hrs), f"a break ending a section before a new page is dropped ({page_hrs})")
v(body_hrs and all(h["display"] != "none" for h in body_hrs), f"a thematic break inside a section prints ({body_hrs})")
v(note_hrs and all(h["display"] != "none" for h in note_hrs), f"the footnote separator prints ({note_hrs})")
v(d["ins"]["boxShadow"] == "none" and "underline" in d["ins"]["line"],
  f"an insertion is underlined without a box-shadow ({d['ins']})")
v(d["strikeColor"] == d["bodyColor"], f"a plain strikethrough keeps the body ink ({d['strikeColor']} vs {d['bodyColor']})")
v(d["abbrAfter"]["display"] == "inline-block", f"an abbreviation's expansion is not underlined with it ({d['abbrAfter']})")
v(d["nestedMarginBottom"] == "0px", f"a nested list adds no gap inside its item ({d['nestedMarginBottom']})")
v(d["lastCellBorderBottom"] not in ("0px", ""), f"a table's last row is closed ({d['lastCellBorderBottom']})")
f = d["figure"]
v(abs(f["leftGap"] - f["rightGap"]) <= 2, f"a figure's image is centred over its caption ({f})")
g = d["groupCaption"]
v(abs(g["width"] - g["groupWidth"]) <= 2 and g["align"] == "center", f"a figure group's caption spans and centres ({g})")
v(d["quotedPreStyle"] == "normal", f"code in a quote is not italic ({d['quotedPreStyle']})")
v(d["titleLabel"] == '"src/Header.php"', f"a fence header prints ({d['titleLabel']})")
for kind in ("tabs", "codeGroups"):
    panels = d[kind]
    v(len(panels) == 2, f"{kind}: 2 panels (saw {len(panels)})")
    for i, p in enumerate(panels, 1):
        v(p["marginTop"] == "0px", f"{kind} panel {i}: no gap above it ({p['marginTop']})")
        v(p["labelPaddingLeft"] not in ("0px", ""), f"{kind} panel {i}: label inset inside its band ({p['labelPaddingLeft']})")
typeset = [m for m in d["math"] if m["katex"]]
if typeset:
    for m in typeset:
        v(m["background"] in ("rgba(0, 0, 0, 0)", "transparent") and m["border"] == "0px",
          f"typeset math drops the TeX-source box ({m})")
else:
    out.append("SKIP\tno KaTeX - typeset math styling is UNMEASURED")
v(d["bylineBreak"] == "avoid", f"the byline keeps with the content above it ({d['bylineBreak']})")
print("\n".join(out))
PY
    while IFS=$'\t' read -r verdict name; do
      [ -n "${name:-}" ] || continue
      case "$verdict" in ok) ok "$name" ;; SKIP) skipd "$name" ;; *) bad "$name" ;; esac
    done < "$WORK/verdicts"
  fi
fi

echo "print styles: passed $pass, failed $fail, skipped $skip"
[ "$fail" -eq 0 ]
