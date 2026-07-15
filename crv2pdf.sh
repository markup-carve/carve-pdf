#!/usr/bin/env bash
#
# crv2pdf - render a Carve (.crv) document to a print-ready PDF.
#
#   crv2pdf <input.crv> [output] [--pdf|--html|--md|--txt]
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

# --- parse args: input, optional output, optional --format flag -------------
FORMAT="pdf"
POS=()
for a in "$@"; do
  case "$a" in
    --pdf|--html|--md|--txt) FORMAT="${a#--}" ;;
    --format=*) FORMAT="${a#--format=}" ;;
    *) POS+=("$a") ;;
  esac
done

IN="${POS[0]:-}"
if [ -z "$IN" ]; then
  echo "usage: crv2pdf <input.crv> [output] [--pdf|--html|--md|--txt]" >&2
  exit 2
fi
if [ ! -f "$IN" ]; then
  echo "crv2pdf: input not found: $IN" >&2
  exit 1
fi
OUT="${POS[1]:-${IN%.*}.$FORMAT}"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/crv2pdf.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
FRAG="$WORK/frag.html"
META="$WORK/meta.json"
DOC="$WORK/doc.html"

# --- pick a renderer backend ------------------------------------------------
RENDERER="${CARVE_RENDERER:-auto}"
if [ "$RENDERER" = "auto" ]; then
  if command -v php >/dev/null 2>&1; then
    RENDERER="php"
  elif command -v node >/dev/null 2>&1; then
    RENDERER="js"
  else
    echo "crv2pdf: no renderer available (need php or node)" >&2
    exit 1
  fi
fi

render() {  # render() <format> -> writes to $FRAG
  case "$RENDERER" in
    php) php "$LIB/render.php" --format "$1" "$IN" > "$FRAG" ;;
    js)  node "$LIB/render.mjs" --format "$1" "$IN" > "$FRAG" ;;
    *)   echo "crv2pdf: unknown CARVE_RENDERER '$RENDERER' (want php|js|auto)" >&2; exit 2 ;;
  esac
}

# --- md / txt: raw renderer output, no wrap/print ---------------------------
if [ "$FORMAT" = "md" ] || [ "$FORMAT" = "txt" ]; then
  render "$FORMAT"
  cp "$FRAG" "$OUT"
  echo "$OUT ($RENDERER backend, $FORMAT)"
  exit 0
fi

# --- html / pdf: render HTML, then wrap -------------------------------------
render html
python3 "$LIB/meta.py" "$IN" > "$META"
SRCDIR="$(cd "$(dirname "$IN")" && pwd)"
python3 "$LIB/wrap.py" "$FRAG" "$META" "$SRCDIR" "$DOC" "$THEMES/base.css" "$THEMES/print.css"

if [ "$FORMAT" = "html" ]; then
  cp "$DOC" "$OUT"
  echo "$OUT ($RENDERER backend, html)"
  exit 0
fi

# --- pdf: footer resolution + Chrome print ----------------------------------
# frontmatter `footer` wins (even when explicitly empty), else print_cdp's
# default chain ($CARVE_PDF_FOOTER, then the English default).
FOOTER_PRESENT="$(python3 -c 'import json,sys; print(int("footer" in json.load(open(sys.argv[1]))))' "$META")"
if [ "$FOOTER_PRESENT" = "1" ]; then
  FOOTER="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["footer"])' "$META")"
  python3 "$LIB/print_cdp.py" "$DOC" "$OUT" "$FOOTER"   # empty string disables the footer
else
  python3 "$LIB/print_cdp.py" "$DOC" "$OUT"
fi

echo "PDF: $OUT ($RENDERER backend)"
