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

# Imported CSS stays after built-in styles and can load its own local assets.
if command -v pdfimages >/dev/null 2>&1; then
  mkdir -p "$WORK/import"
  python3 - "$WORK/import/red.png" <<'PY'
import struct, sys, zlib
def chunk(kind, data):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
raw = b''.join(b'\x00' + b'\xff\x00\x00' * 16 for _ in range(16))
png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 16, 16, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b'')
open(sys.argv[1], 'wb').write(png)
PY
  printf '# CSS import\n\nBody.\n' > "$WORK/import/input.crv"
  printf '%s\n' '@import "imported.css";' > "$WORK/import/host.css"
  printf '%s\n' 'body::before { content:""; display:block; width:64px; height:64px; background: url("red.png") 0 0 / 64px 64px no-repeat; }' > "$WORK/import/imported.css"
  if "$HERE/crv2pdf.sh" --css "$WORK/import/host.css" "$WORK/import/input.crv" \
      "$WORK/import/out.pdf" > "$WORK/import/render.log" 2>&1 && \
      pdfimages -list "$WORK/import/out.pdf" | awk 'NR > 2 && $3 == "image" { found=1 } END { exit !found }'; then
    echo 'theme snapshot: ok imported CSS loaded its local image'
  else
    echo 'theme snapshot: FAIL imported CSS image was not embedded'
    cat "$WORK/import/render.log"
    fail=1
  fi
fi
exit "$fail"
