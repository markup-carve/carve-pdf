#!/usr/bin/env bash
#
# crv2pdf - render a Carve (.crv) document to a print-ready PDF.
#
#   crv2pdf <input.crv> [output.pdf]
#
# Pipeline:  render.php (Carve -> faithful HTML) | wrap.py (+ frontmatter + CSS)
#            | print_cdp.py (Chrome DevTools -> PDF with page numbers).
#
# Env:
#   CARVE_PHP_AUTOLOAD  composer autoloader providing MarkupCarve\Carve
#   CARVE_SMART_LOCALE  smart-quotes locale (default: en)
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

IN="${1:-}"
if [ -z "$IN" ]; then
  echo "usage: crv2pdf <input.crv> [output.pdf]" >&2
  exit 2
fi
if [ ! -f "$IN" ]; then
  echo "crv2pdf: input not found: $IN" >&2
  exit 1
fi
OUT="${2:-${IN%.*}.pdf}"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/crv2pdf.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
FRAG="$WORK/frag.html"
META="$WORK/meta.json"
DOC="$WORK/doc.html"

php "$LIB/render.php" "$IN" > "$FRAG"
php "$LIB/render.php" --meta "$IN" > "$META"
SRCDIR="$(cd "$(dirname "$IN")" && pwd)"
python3 "$LIB/wrap.py" "$FRAG" "$META" "$SRCDIR" "$DOC" "$THEMES/base.css" "$THEMES/print.css"
python3 "$LIB/print_cdp.py" "$DOC" "$OUT"

echo "PDF: $OUT"
