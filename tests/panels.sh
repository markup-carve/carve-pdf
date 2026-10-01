#!/usr/bin/env bash
#
# Panel visibility gate.
#
# A tab set and a code group are the two constructs the stylesheet can hide
# outright, and a text assertion over the CSS cannot tell: `display: none` with
# no rule reaching it, a zero height and a cover drawn on top all read the same
# in the source. So this gate renders the fixture through the real pipeline and
# asks a browser, then asks the printed PDF.
#
# Skips cleanly when Chrome or websocket-client is absent, and says so rather
# than reporting success over a surface it never rendered.
set -uo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
LIB="$HERE/lib"
FIX="$HERE/tests/fixtures/panels.crv"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

pass=0; fail=0; skip=0
ok()   { echo "  ok   - $1"; pass=$((pass+1)); }
bad()  { echo "  FAIL - $1"; fail=$((fail+1)); }
skipd(){ echo "  skip - $1"; skip=$((skip+1)); }

MARKERS=(PANELBODYALPHA PANELBODYBETA PANELBODYGAMMA PANELBODYDELTA)

have_chrome() {
  [ -n "${CHROME_BIN:-}" ] && command -v "$CHROME_BIN" >/dev/null 2>&1 && return 0
  command -v google-chrome >/dev/null 2>&1 || command -v chromium >/dev/null 2>&1 \
    || command -v chromium-browser >/dev/null 2>&1
}

echo "== panels: rendered page (computed style) =="
if ! have_chrome; then
  skipd "no Chrome binary - panel visibility is UNMEASURED"
elif ! python3 -c 'import websocket' 2>/dev/null; then
  skipd "no websocket-client - panel visibility is UNMEASURED"
else
  html="$WORK/panels.html"
  if ! "$HERE/crv2pdf.sh" "$FIX" "$html" --html >/dev/null 2>&1; then
    bad "could not render the fixture to HTML"
  elif ! python3 "$LIB/probe_cdp.py" "$html" "$HERE/tests/panels.js" > "$WORK/probe.json" 2>"$WORK/probe.err"; then
    bad "probe_cdp.py failed: $(tr -d '\n' < "$WORK/probe.err" | cut -c1-200)"
  else
    # One python pass over the probe record; prints a tab-separated verdict line
    # per assertion so the shell stays the place that counts.
    python3 - "$WORK/probe.json" > "$WORK/verdicts" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding='utf-8'))
out = []
def v(ok, name): out.append(("ok" if ok else "FAIL") + "\t" + name)

sets = [("tab", d["tabsPanels"], 2), ("code group", d["codeGroupPanels"], 2)]
for kind, panels, want in sets:
    v(len(panels) == want, f"{kind}: {want} panels in the DOM (saw {len(panels)})")
    for i, p in enumerate(panels, 1):
        at = f"{kind} panel {i}"
        v(p["display"] != "none", f"{at}: display is not none (is {p['display']})")
        v(p["visible"] is not False, f"{at}: the browser reports it visible ({p['visible']})")
        v(p["hiddenBy"] is None, f"{at}: not hidden by an ancestor ({p['hiddenBy']})")
        v(not p["hiddenAttr"], f"{at}: carries no `hidden` attribute")
        v(p["height"] > 0, f"{at}: height {p['height']}px is above zero")
        v(p["occludedBy"] is None, f"{at}: nothing drawn over it ({p['occludedBy']})")
        # Not `bool(p["body"])`: a hidden panel still reports its text.
        v(p["bodyRendered"], f"{at}: body text actually RENDERED ({p['body'][:40]!r})")
        # Distinguishable = not just another line of body text.
        differs = (p["labelWeight"] != p["bodyWeight"]
                   or p["labelColor"] != p["bodyColor"]
                   or p["labelSize"] != p["bodySize"])
        v(bool(p["label"]) and differs,
          f"{at}: label {p['label']!r} is distinguishable from the body "
          f"(weight {p['labelWeight']} vs {p['bodyWeight']}, size {p['labelSize']} vs {p['bodySize']})")

for m in d["markers"]:
    v(m["inRenderedText"], f"marker {m['marker']} is in the rendered text")

# Interactive shape, when the document has one. Static mode has no controls, and
# an absent set is reported rather than silently passing.
controls = d["controls"]
if controls:
    checked = [c for c in controls if c["checked"]]
    v(len(checked) >= 1, f"a control is selected ({len(checked)} of {len(controls)})")
    unchecked = [c for c in controls if not c["checked"]]
    if checked and unchecked:
        a, b = checked[0], unchecked[0]
        v(a["labelColor"] != b["labelColor"] or a["labelBorderColor"] != b["labelBorderColor"]
          or a["labelWeight"] != b["labelWeight"],
          f"the selected control is distinguishable (color {a['labelColor']} vs {b['labelColor']}, "
          f"border {a['labelBorderColor']} vs {b['labelBorderColor']})")
print("\n".join(out))
PY
    while IFS=$'\t' read -r verdict name; do
      [ -n "${name:-}" ] || continue
      if [ "$verdict" = "ok" ]; then ok "$name"; else bad "$name"; fi
    done < "$WORK/verdicts"
    if [ -z "$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["controls"])' "$WORK/probe.json" 2>/dev/null | tr -d '[]')" ]; then
      echo "  note - static render mode: no radio controls in this document"
    fi
  fi
fi

echo "== panels: printed PDF (extracted text) =="
if ! have_chrome; then
  skipd "no Chrome binary - PDF panel text is UNMEASURED"
elif ! command -v pdftotext >/dev/null 2>&1; then
  skipd "no pdftotext (poppler-utils) - PDF panel text is UNMEASURED"
else
  pdf="$WORK/panels.pdf"
  if ! "$HERE/crv2pdf.sh" "$FIX" "$pdf" --pdf >/dev/null 2>&1; then
    bad "could not print the fixture to PDF"
  else
    pdftotext "$pdf" "$WORK/panels.txt" 2>/dev/null
    for m in "${MARKERS[@]}"; do
      if grep -qF -- "$m" "$WORK/panels.txt"; then
        ok "PDF carries $m"
      else
        bad "PDF is missing $m (a hidden panel contributes no text)"
      fi
    done
  fi
fi

echo "panels: passed $pass, failed $fail, skipped $skip"
[ "$fail" -eq 0 ]
