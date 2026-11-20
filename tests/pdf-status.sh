#!/usr/bin/env bash
# Exercise the CLI output contract without depending on a particular browser.
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/carve-pdf-status.XXXXXX")"
REAL_PYTHON="$(command -v python3)"
REAL_NODE="$(command -v node)"
REAL_PHP="$(command -v php)"
export REAL_PYTHON REAL_NODE REAL_PHP
REAL_PATH="$PATH"
mkdir -p "$WORK/bin"
cat > "$WORK/bin/python3" <<'EOF'
#!/usr/bin/env bash
if [ "$1" = -c ] && [ "$2" = 'import websocket' ]; then exit 0; fi
if [[ "$1" = */print_cdp.py ]]; then
  case "$FAKE_PRINT" in
    missing) exit 0 ;;
    invalid) printf 'not a PDF\n' > "$3"; exit 0 ;;
    fail) echo 'printer failed' >&2; exit 1 ;;
    good) printf '%%PDF-1.4\n%%test\n' > "$3"; exit 0 ;;
  esac
fi
exec "$REAL_PYTHON" "$@"
EOF
chmod +x "$WORK/bin/python3"
printf 'A document.\n' > "$WORK/input.crv"
export PATH="$WORK/bin:$PATH"
export CARVE_RENDERER="${CARVE_RENDERER:-js}"

cat > "$WORK/bin/node" <<'EOF'
#!/usr/bin/env bash
if [ "${FAKE_NO_BACKEND:-0}" = 1 ]; then exit 1; fi
exec "$REAL_NODE" "$@"
EOF
cat > "$WORK/bin/php" <<'EOF'
#!/usr/bin/env bash
if [ "${FAKE_NO_BACKEND:-0}" = 1 ]; then exit 1; fi
exec "$REAL_PHP" "$@"
EOF
chmod +x "$WORK/bin/node" "$WORK/bin/php"

if FAKE_NO_BACKEND=1 CARVE_RENDERER=auto "$HERE/crv2pdf.sh" \
  "$WORK/input.crv" "$WORK/no-backend.pdf" --pdf > "$WORK/log" 2>&1; then
  echo 'FAIL: no renderer returned success' >&2; exit 1
fi
grep -qF 'no usable Carve renderer backend' "$WORK/log"
[ ! -e "$WORK/no-backend.pdf" ]
echo 'ok: no renderer exits nonzero with a message'

mkdir -p "$WORK/output-dir.pdf"
if "$HERE/crv2pdf.sh" "$WORK/input.crv" "$WORK/output-dir.pdf" --pdf > "$WORK/log" 2>&1; then
  echo 'FAIL: output directory returned success' >&2; exit 1
fi
grep -qF 'output path is a directory' "$WORK/log"
echo 'ok: directory cannot count as an output file'

check_failure() {
  local label="$1" expected="$2"
  if "$HERE/crv2pdf.sh" "$WORK/input.crv" "$WORK/output.pdf" --pdf > "$WORK/log" 2>&1; then
    echo "FAIL: $label returned success" >&2; exit 1
  fi
  if ! grep -qF "$expected" "$WORK/log"; then
    echo "FAIL: $label has no useful error" >&2; cat "$WORK/log" >&2; exit 1
  fi
  echo "ok: $label"
}

export FAKE_PRINT=missing
check_failure 'no PDF written' 'printer did not write a PDF'
[ ! -e "$WORK/output.pdf" ]

export FAKE_PRINT=invalid
check_failure 'invalid printer output' 'printer did not write a PDF'
[ ! -e "$WORK/output.pdf" ]

export FAKE_PRINT=good
printf 'old output\n' > "$WORK/output.pdf"
"$HERE/crv2pdf.sh" "$WORK/input.crv" "$WORK/output.pdf" --pdf > "$WORK/log" 2>&1
[ -f "$WORK/output.pdf" ]
[ "$(head -c 4 "$WORK/output.pdf")" = '%PDF' ]
echo 'ok: successful PDF has a PDF signature'

if [ "$(id -u)" -ne 0 ]; then
  mkdir -p "$WORK/no-write"
  chmod 500 "$WORK/no-write"
  if "$HERE/crv2pdf.sh" "$WORK/input.crv" "$WORK/no-write/new.pdf" --pdf > "$WORK/log" 2>&1; then
    echo 'FAIL: publication into an unwritable directory returned success' >&2; exit 1
  fi
  grep -qF 'cannot write PDF' "$WORK/log"
  [ ! -e "$WORK/no-write/new.pdf" ]
  chmod 700 "$WORK/no-write"
  echo 'ok: failed publication exits nonzero with a message'
fi

export FAKE_PRINT=missing
check_failure 'stale PDF does not count' 'printer did not write a PDF'
[ "$(head -c 4 "$WORK/output.pdf")" = '%PDF' ]

export FAKE_PRINT=fail
check_failure 'printer failure' 'PDF printing failed'

printf 'Another document.\n' > "$WORK/second.crv"
if "$HERE/crv2pdf.sh" --out-dir "$WORK/batch" --pdf \
  "$WORK/input.crv" "$WORK/second.crv" > "$WORK/log" 2>&1; then
  echo 'FAIL: batch accepted failed PDF prints' >&2; exit 1
fi
grep -qF 'PDF printing failed' "$WORK/log"
[ ! -e "$WORK/batch/input.pdf" ]
[ ! -e "$WORK/batch/second.pdf" ]
echo 'ok: batch failure exits nonzero'

if "$HERE/crv2pdf.sh" --watch "$WORK/input.crv" "$WORK/watch.pdf" --pdf > "$WORK/log" 2>&1; then
  echo 'FAIL: watch accepted its failed initial build' >&2; exit 1
fi
grep -qF 'PDF printing failed' "$WORK/log"
echo 'ok: watch initial failure exits nonzero'

if { [ -n "${CHROME_BIN:-}" ] || command -v google-chrome >/dev/null 2>&1 || \
     command -v chromium >/dev/null 2>&1; } && \
   "$REAL_PYTHON" -c 'import websocket' 2>/dev/null; then
  if ! PATH="$REAL_PATH" "$HERE/crv2pdf.sh" "$WORK/input.crv" "$WORK/real.pdf" --pdf > "$WORK/log" 2>&1; then
    cat "$WORK/log" >&2; exit 1
  fi
  if [ ! -f "$WORK/real.pdf" ] || [ "$(head -c 4 "$WORK/real.pdf")" != '%PDF' ]; then
    echo 'FAIL: Chromium did not write a PDF' >&2; cat "$WORK/log" >&2; exit 1
  fi
  echo 'ok: Chromium wrote a PDF with the expected signature'
else
  echo 'skip: Chromium PDF check (browser or websocket-client unavailable)'
fi
