#!/usr/bin/env bash
#
# crv2pdf - render Carve (.crv) documents to PDF / HTML / Markdown / text.
#
#   crv2pdf <input.crv> [output] [--pdf|--html|--md|--txt]   single file
#   crv2pdf a.crv b.crv ...        [--out-dir DIR] [--fmt]     batch
#   crv2pdf --watch <input.crv> [output] [--fmt]               rebuild on change
#
# Output format (default --pdf):
#   --pdf   paginated PDF (render -> wrap -> Chrome print)
#   --html  standalone styled HTML document (render -> wrap)
#   --md    Markdown
#   --txt   plain text
#
# Pipeline:  render.php / render.mjs (Carve -> HTML) | wrap.py (+ frontmatter + CSS)
#            | print_cdp.py (Chrome DevTools -> PDF with page numbers).
#
# Env:
#   CARVE_RENDERER      php | js | auto (default auto: php if available, else js)
#   CARVE_PHP_AUTOLOAD  composer autoloader providing MarkupCarve\Carve (php backend)
#   CARVE_JS            carve-js checkout or dist/index.js (js backend)
#   CARVE_KATEX         KaTeX dist/ dir for math typesetting (default: autodetect)
#   CARVE_SMART_LOCALE  smart-quotes locale (default: en)
#   CARVE_PDF_FOOTER    footer template with {page}/{pages} (default: Page {page} of {pages});
#                       frontmatter `footer:` wins over this; empty string disables the footer
#   CHROME_BIN          Chrome/Chromium binary (default: autodetect)
set -euo pipefail

# Resolve through symlinks so a `~/.local/bin/crv2pdf` symlink still finds lib/ + themes/.
SELF="${BASH_SOURCE[0]}"
if command -v readlink >/dev/null 2>&1; then
  SELF="$(readlink -f "$SELF" 2>/dev/null || echo "$SELF")"
fi
HERE="$(cd "$(dirname "$SELF")" && pwd)"
LIB="$HERE/lib"
THEMES="$HERE/themes"

# --- parse args -------------------------------------------------------------
FORMAT="pdf"
WATCH=0
OUT_DIR=""
POS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --pdf|--html|--md|--txt) FORMAT="${1#--}" ;;
    --format=*) FORMAT="${1#--format=}" ;;
    --watch|-w) WATCH=1 ;;
    --out-dir) OUT_DIR="${2:-}"; shift ;;
    --out-dir=*) OUT_DIR="${1#--out-dir=}" ;;
    *) POS+=("$1") ;;
  esac
  shift
done

usage() { echo "usage: crv2pdf <input.crv> [output] [--pdf|--html|--md|--txt] [--watch] [--out-dir DIR]" >&2; exit 2; }
[ ${#POS[@]} -ge 1 ] || usage

# Batch mode iff --out-dir is set, or several positionals that ALL end in .crv
# (so `crv2pdf input.crv output.pdf` stays single-file - output.pdf isn't .crv -
# even when output.pdf already exists). Otherwise single-file, with an optional
# explicit output as the 2nd positional.
BATCH=0
if [ -n "$OUT_DIR" ]; then
  BATCH=1
elif [ ${#POS[@]} -gt 1 ]; then
  ALL_CRV=1
  for p in "${POS[@]}"; do case "$p" in *.crv) ;; *) ALL_CRV=0 ;; esac; done
  [ $ALL_CRV -eq 1 ] && BATCH=1
fi

# --- pick a renderer backend ------------------------------------------------
RENDERER="${CARVE_RENDERER:-auto}"
if [ "$RENDERER" = "auto" ]; then
  if command -v php >/dev/null 2>&1; then RENDERER="php"
  elif command -v node >/dev/null 2>&1; then RENDERER="js"
  else echo "crv2pdf: no renderer available (need php or node)" >&2; exit 1; fi
fi

WORK="$(mktemp -d "${TMPDIR:-/tmp}/crv2pdf.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

render() {  # render() <in> <format> -> writes $WORK/frag
  case "$RENDERER" in
    php) php "$LIB/render.php" --format "$2" "$1" > "$WORK/frag" ;;
    js)  node "$LIB/render.mjs" --format "$2" "$1" > "$WORK/frag" ;;
    *)   echo "crv2pdf: unknown CARVE_RENDERER '$RENDERER' (want php|js|auto)" >&2; exit 2 ;;
  esac
}

build_one() {  # build_one <input.crv> <output>
  local in="$1" out="$2"
  if [ ! -f "$in" ]; then echo "crv2pdf: input not found: $in" >&2; return 1; fi

  if [ "$FORMAT" = "md" ] || [ "$FORMAT" = "txt" ]; then
    render "$in" "$FORMAT"
    cp "$WORK/frag" "$out"
    echo "$out ($RENDERER backend, $FORMAT)"
    return 0
  fi

  render "$in" html
  python3 "$LIB/meta.py" "$in" > "$WORK/meta.json"
  local srcdir; srcdir="$(cd "$(dirname "$in")" && pwd)"
  python3 "$LIB/wrap.py" "$WORK/frag" "$WORK/meta.json" "$srcdir" "$WORK/doc.html" \
    "$THEMES/base.css" "$THEMES/print.css"

  if [ "$FORMAT" = "html" ]; then
    cp "$WORK/doc.html" "$out"
    echo "$out ($RENDERER backend, html)"
    return 0
  fi

  # pdf: frontmatter `footer` wins (even when explicitly empty), else print_cdp's
  # default chain ($CARVE_PDF_FOOTER, then the English default).
  local present; present="$(python3 -c 'import json,sys; print(int("footer" in json.load(open(sys.argv[1]))))' "$WORK/meta.json")"
  if [ "$present" = "1" ]; then
    local footer; footer="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["footer"])' "$WORK/meta.json")"
    python3 "$LIB/print_cdp.py" "$WORK/doc.html" "$out" "$footer"
  else
    python3 "$LIB/print_cdp.py" "$WORK/doc.html" "$out"
  fi
  echo "PDF: $out ($RENDERER backend)"
}

out_for() {  # out_for <input> -> derived output path
  local in="$1" base
  base="$(basename "${in%.*}").$FORMAT"
  if [ -n "$OUT_DIR" ]; then mkdir -p "$OUT_DIR"; echo "$OUT_DIR/$base";
  else echo "$(dirname "$in")/$base"; fi
}

# --- watch mode -------------------------------------------------------------
if [ "$WATCH" = "1" ]; then
  [ ${#POS[@]} -le 2 ] || { echo "crv2pdf: --watch takes one input (and an optional output)" >&2; exit 2; }
  IN="${POS[0]}"
  OUT="$(out_for "$IN")"; [ -n "$OUT_DIR" ] || OUT="${POS[1]:-$OUT}"
  build_one "$IN" "$OUT" || true
  echo "[watch] $IN -> $OUT (Ctrl-C to stop)"
  dir="$(cd "$(dirname "$IN")" && pwd)"; base="$(basename "$IN")"

  mtime() {  # portable mtime in epoch seconds
    stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null || echo 0
  }

  if command -v inotifywait >/dev/null 2>&1; then
    # event-driven (blocks on inotify events, no sleep-poll)
    inotifywait -m -q -e close_write,moved_to,create --format '%f' "$dir" | while read -r f; do
      [ "$f" = "$base" ] && { echo "[rebuild $(date +%T)]"; build_one "$IN" "$OUT" || true; }
    done
  else
    # portable fallback: 1s mtime poll
    last="$(mtime "$IN")"
    while true; do
      sleep 1
      now="$(mtime "$IN")"
      if [ "$now" != "$last" ]; then
        last="$now"; echo "[rebuild $(date +%T)]"; build_one "$IN" "$OUT" || true
      fi
    done
  fi
  exit 0
fi

# --- batch mode -------------------------------------------------------------
if [ "$BATCH" = "1" ]; then
  rc=0
  for in in "${POS[@]}"; do
    build_one "$in" "$(out_for "$in")" || rc=1
  done
  exit $rc
fi

# --- single-file mode -------------------------------------------------------
IN="${POS[0]}"
OUT="${POS[1]:-${IN%.*}.$FORMAT}"
build_one "$IN" "$OUT"
