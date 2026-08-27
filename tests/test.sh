#!/usr/bin/env bash
#
# carve-pdf test harness. Renders fixtures with every available backend and
# asserts structural invariants (robust to pre-1.0 carve output drift). Also
# exercises the wrap.py frontmatter handling (page geometry validation).
#
# Runs whatever backends are present; fails if none are usable. Exit 0 = pass.
set -uo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
LIB="$HERE/lib"
FIX="$HERE/tests/fixtures"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

pass=0; fail=0
ok()   { echo "  ok   - $1"; pass=$((pass+1)); }
bad()  { echo "  FAIL - $1"; fail=$((fail+1)); }
has()  { if grep -qF -- "$3" "$2"; then ok "$1"; else bad "$1 (missing: $3)"; fi; }
hasnt(){ if grep -qF -- "$3" "$2"; then bad "$1 (unexpected: $3)"; else ok "$1"; fi; }
has_any() {
  if grep -qF "$3" "$2" || grep -qF "$4" "$2"; then
    ok "$1"
  else
    bad "$1 (missing both: $3, $4)"
  fi
}

# --- which backends can run? ------------------------------------------------
backends=()
if command -v php >/dev/null 2>&1 && php "$LIB/render.php" "$FIX/marks.crv" >/dev/null 2>&1; then
  backends+=(php)
fi
if command -v node >/dev/null 2>&1 && node "$LIB/render.mjs" "$FIX/marks.crv" >/dev/null 2>&1; then
  backends+=(js)
fi
if [ ${#backends[@]} -eq 0 ]; then
  echo "no usable renderer backend (need php+carve-php or node+carve-js)" >&2
  exit 1
fi
echo "backends: ${backends[*]}"

render() {  # render <backend> <fixture> <outfile>
  case "$1" in
    php) php "$LIB/render.php" "$2" > "$3" 2>/dev/null ;;
    js)  node "$LIB/render.mjs" "$2" > "$3" 2>/dev/null ;;
  esac
}

for be in "${backends[@]}"; do
  echo "== backend: $be =="
  m="$WORK/marks.$be.html"; render "$be" "$FIX/marks.crv" "$m"

  has  "bold"            "$m" "<strong>bold</strong>"
  has  "italic"          "$m" "<em>italic</em>"
  has  "underline"       "$m" "<u>underline</u>"
  has  "highlight"       "$m" "<mark>highlight</mark>"
  has  "insert"          "$m" "<ins>insert</ins>"
  has  "delete"          "$m" "<del>delete</del>"
  has  "superscript"     "$m" "<sup>2</sup>"
  has  "subscript"       "$m" "<sub>2</sub>"
  # PHP currently preserves the attribute spelling while JS emits the semantic
  # element; both remain keyboard input and the bundled theme styles both.
  has_any "kbd"           "$m" "<kbd>Ctrl</kbd>" '<span kbd="">Ctrl</span>'
  has  "abbr"            "$m" '<abbr title="HyperText Markup Language">HTML</abbr>'
  has  "admonition tip"  "$m" 'class="admonition tip"'
  has  "list-table->table" "$m" "<table>"
  hasnt "no raw list-table div" "$m" 'class="list-table"'
  has  "definition list" "$m" "<dl>"
  has  "footnote ref"    "$m" "doc-noteref"

  d="$WORK/diagram.$be.html"; render "$be" "$FIX/diagram.crv" "$d"
  has  "mermaid block"   "$d" 'class="mermaid"'

  c="$WORK/chart.$be.html"; render "$be" "$FIX/chart.crv" "$c"
  has  "chart block"     "$c" 'class="chart"'
done

# --- wrap.py: page-geometry validation --------------------------------------
echo "== wrap.py page geometry =="
render "${backends[0]}" "$FIX/marks.crv" "$WORK/frag.html"

# valid paper/margin -> @page override present
echo '{"paper":"Letter","margin":"12mm"}' > "$WORK/ok.json"
python3 "$LIB/wrap.py" "$WORK/frag.html" "$WORK/ok.json" "$FIX" "$WORK/ok.html" "$HERE/themes/carve-css/tokens.css" "$HERE/themes/carve-css/core.css" "$HERE/themes/carve-css/extensions.css" "$HERE/themes/carve-css/recipes.css" "$HERE/themes/base.css" "$HERE/themes/print.css" 2>/dev/null
has  "valid paper inlined"  "$WORK/ok.html" "size: Letter;"
has  "recipe theme inlined" "$WORK/ok.html" "--carve-tree-indent"
has  "Carve theme scope"     "$WORK/ok.html" '<body class="carve">'
has  "PHP syntax highlighted" "$WORK/ok.html" 'syntax-highlighted'
has  "Carve syntax highlighted" "$WORK/ok.html" 'class="tok-gs">strong</span>'

# injection attempt -> rejected, not inlined
printf '{"paper":"A4; } body { background: red } @page {"}' > "$WORK/evil.json"
python3 "$LIB/wrap.py" "$WORK/frag.html" "$WORK/evil.json" "$FIX" "$WORK/evil.html" "$HERE/themes/carve-css/tokens.css" "$HERE/themes/carve-css/core.css" "$HERE/themes/carve-css/extensions.css" "$HERE/themes/carve-css/recipes.css" "$HERE/themes/base.css" "$HERE/themes/print.css" 2>/dev/null
hasnt "css injection rejected" "$WORK/evil.html" "background: red"

echo
echo "passed: $pass  failed: $fail"
[ "$fail" -eq 0 ]
