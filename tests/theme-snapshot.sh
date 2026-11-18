#!/usr/bin/env bash
# Bundled classic theme: page-count and extracted-text snapshots over examples.
set -uo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
if ! command -v pdfinfo >/dev/null 2>&1 || ! command -v pdftotext >/dev/null 2>&1 || \
   ! python3 -c 'import websocket' 2>/dev/null || \
   ! { command -v google-chrome >/dev/null 2>&1 || command -v google-chrome-stable >/dev/null 2>&1 || command -v chromium >/dev/null 2>&1; }; then
  echo "theme snapshot: skip (needs Chrome, websocket-client, and poppler)"
  exit 0
fi
WORK="$(mktemp -d)"
fail=0
for row in '01-spec:2:Carve Engineering Spec' '02-showcase:1:Feature Showcase'; do
  name="${row%%:*}"
  rest="${row#*:}"
  pages="${rest%%:*}"
  needle="${rest#*:}"
  if ! "$HERE/crv2pdf.sh" --theme classic "$HERE/examples/$name.crv" "$WORK/$name.pdf" > "$WORK/$name.log" 2>&1; then
    echo "theme snapshot: FAIL $name did not print"
    cat "$WORK/$name.log"
    fail=1
    continue
  fi
  actual="$(pdfinfo "$WORK/$name.pdf" | awk '/^Pages:/ { print $2 }')"
  pdftotext "$WORK/$name.pdf" "$WORK/$name.txt"
  if [ "$actual" != "$pages" ] || ! grep -qF "$needle" "$WORK/$name.txt" || \
     ! grep -qF "Page $pages of $pages" "$WORK/$name.txt"; then
    echo "theme snapshot: FAIL $name ($actual pages, expected $pages; text or footer missing)"
    fail=1
  else
    echo "theme snapshot: ok $name ($pages pages, extracted text and footer)"
  fi
done
exit "$fail"
