#!/usr/bin/env bash
#
# Code listing layout gate: a captioned listing is not centered, a long line is
# not clipped, and a lead-in paragraph stays with its listing. Alignment and the
# break hint are asked of a browser; clipping is checked on the printed PDF,
# because the probe's viewport is wider than an A4 page and cannot clip.
#
# Skips cleanly when Chrome or websocket-client is absent, and says so.
set -uo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
LIB="$HERE/lib"
FIX="$HERE/tests/fixtures/listings.crv"
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

echo "== listings: rendered page (computed style) =="
if ! have_chrome; then
  skipd "no Chrome binary - listing layout is UNMEASURED"
elif ! python3 -c 'import websocket' 2>/dev/null; then
  skipd "no websocket-client - listing layout is UNMEASURED"
else
  html="$WORK/listings.html"
  if ! "$HERE/crv2pdf.sh" "$FIX" "$html" --html >/dev/null 2>&1; then
    bad "could not render the fixture to HTML"
  elif ! python3 "$LIB/probe_cdp.py" "$html" "$HERE/tests/listings.js" > "$WORK/probe.json" 2>"$WORK/probe.err"; then
    bad "probe_cdp.py failed: $(tr -d '\n' < "$WORK/probe.err" | cut -c1-200)"
  else
    python3 - "$WORK/probe.json" > "$WORK/verdicts" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding='utf-8'))
out = []
def v(ok, name): out.append(("ok" if ok else "FAIL") + "\t" + name)

listings = d["listings"]
v(len(listings) == 2, f"2 listings in the DOM (saw {len(listings)})")
v(any(l["inFigure"] for l in listings), "one listing is wrapped in a captioned figure")
for i, l in enumerate(listings, 1):
    at = f"listing {i}" + (" (captioned)" if l["inFigure"] else "")
    for part in ("pre", "code"):
        align = l[part + "Align"]
        v(align in ("left", "start"), f"{at}: {part} is left-aligned (is {align})")
    v(l["leadIn"] is not None, f"{at}: has a lead-in paragraph")
    v(l["leadInBreakAfter"] == "avoid",
      f"{at}: lead-in {l['leadIn']!r} keeps with the listing (break-after {l['leadInBreakAfter']})")
    # Keeping the lead-in with its block must not push the break INTO a
    # two-line lead-in instead.
    v(l["leadInBreakInside"] == "avoid",
      f"{at}: lead-in is not split across pages (break-inside {l['leadInBreakInside']})")
print("\n".join(out))
PY
    while IFS=$'\t' read -r verdict name; do
      [ -n "${name:-}" ] || continue
      if [ "$verdict" = "ok" ]; then ok "$name"; else bad "$name"; fi
    done < "$WORK/verdicts"
  fi
fi

echo "== listings: printed PDF (extracted text) =="
if ! have_chrome; then
  skipd "no Chrome binary - PDF listing text is UNMEASURED"
elif ! command -v pdftotext >/dev/null 2>&1; then
  skipd "no pdftotext (poppler-utils) - PDF listing text is UNMEASURED"
else
  pdf="$WORK/listings.pdf"
  if ! "$HERE/crv2pdf.sh" "$FIX" "$pdf" --pdf >/dev/null 2>&1; then
    bad "could not print the fixture to PDF"
  else
    pdftotext "$pdf" "$WORK/listings.txt" 2>/dev/null
    # The line ends in "than that"; a clipped line loses its tail on paper.
    if grep -qF -- "than that" "$WORK/listings.txt"; then
      ok "PDF carries the end of the long line"
    else
      bad "PDF is missing the end of the long line (clipped at the margin)"
    fi
  fi
fi

echo "listings: passed $pass, failed $fail, skipped $skip"
[ "$fail" -eq 0 ]
