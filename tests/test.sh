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

# --- includes ----------------------------------------------------------------
INC="$WORK/inc"
mkdir -p "$INC/doc/sub" "$INC/outside"
printf 'SECRET-OUTSIDE\n' > "$INC/outside/secret.crv"
ln -s ../outside/secret.crv "$INC/doc/link.crv"
printf 'Beta nested\n' > "$INC/doc/sub/b.crv"
printf 'Alpha\n\n{{ b.crv }}\n\n{{ gone.crv }}\n' > "$INC/doc/sub/a.crv"
printf 'Top\n\n{{ sub/a.crv }}\n' > "$INC/doc/nested.crv"
printf '{{ ../outside/secret.crv }}\n' > "$INC/doc/escape.crv"
printf '{{ link.crv }}\n' > "$INC/doc/symlink.crv"
printf 'Cycle one\n\n{{ c2.crv }}\n' > "$INC/doc/c1.crv"
printf 'Cycle two\n\n{{ c1.crv }}\n' > "$INC/doc/c2.crv"

for be in "${backends[@]}"; do
  echo "== includes: $be =="
  case "$be" in php) R=(php "$LIB/render.php") ;; js) R=(node "$LIB/render.mjs") ;; esac
  o="$WORK/inc.$be"

  "${R[@]}" --deps "$o.deps" "$INC/doc/nested.crv" > "$o.nested" 2> "$o.nested.err"
  has   "nested relative include expands"     "$o.nested" "Beta nested"
  has   "missing target reports itself"       "$o.nested.err" "[include-unresolved]"
  has   "warning names the file root-relative" "$o.nested.err" "in sub/a.crv"
  has   "missing target stays literal"        "$o.nested" "{{ gone.crv }}"
  hasnt "no host path in warnings"            "$o.nested.err" "$INC"
  if [ "$(cat "$o.deps")" = "$(printf 'sub/a.crv\nsub/b.crv')" ]; then ok "deps are the files read, root-relative"
  else bad "deps are the files read, root-relative (got: $(tr '\n' ' ' < "$o.deps"))"; fi

  "${R[@]}" --format md "$INC/doc/nested.crv" > "$o.md" 2>/dev/null
  has   "md output expands too"               "$o.md" "Beta nested"

  "${R[@]}" "$INC/doc/escape.crv" > "$o.escape" 2> "$o.escape.err"
  hasnt "traversal out of the input dir refused" "$o.escape" "SECRET-OUTSIDE"
  has   "traversal refusal reports itself"    "$o.escape.err" "[include-unresolved]"

  "${R[@]}" "$INC/doc/symlink.crv" > "$o.symlink" 2>/dev/null
  hasnt "symlink escape refused"              "$o.symlink" "SECRET-OUTSIDE"

  "${R[@]}" --include-root "$INC" "$INC/doc/escape.crv" > "$o.wide" 2>/dev/null
  has   "explicit root widens containment"    "$o.wide" "SECRET-OUTSIDE"

  "${R[@]}" --include-root "$INC" "$INC/doc/nested.crv" > "$o.wide.nested" 2>/dev/null
  has   "top-level path resolves against the input, not the root" "$o.wide.nested" "Beta nested"

  # A typed root resolves against the cwd: "." read against the input's directory would not reach ../outside.
  (cd "$INC" && "${R[@]}" --include-root . doc/escape.crv) > "$o.rel" 2> "$o.rel.err"
  has   "relative root resolves against the cwd" "$o.rel" "SECRET-OUTSIDE"

  "${R[@]}" --no-includes --deps "$o.off.deps" "$INC/doc/nested.crv" > "$o.off" 2> "$o.off.err"
  has   "--no-includes leaves directives literal" "$o.off" "{{ sub/a.crv }}"
  hasnt "--no-includes warns about nothing"   "$o.off.err" "include-"
  if [ ! -s "$o.off.deps" ]; then ok "--no-includes records no deps"; else bad "--no-includes records no deps"; fi

  "${R[@]}" "$INC/doc/c1.crv" > "$o.cycle" 2> "$o.cycle.err"
  has   "cycle reports itself"                "$o.cycle.err" "[include-cycle]"
  has   "cycle still renders the chain once"  "$o.cycle" "Cycle two"
done

# An engine that predates includes must say so rather than render directives as prose.
echo "== includes: engine without include support =="
if [ -n "${CARVE_PHP_AUTOLOAD:-}" ] && [[ " ${backends[*]} " == *" php "* ]]; then
  cat > "$WORK/old-autoload.php" <<'EOF'
<?php
$loader = require getenv('REAL_AUTOLOAD');
$loader->unregister();
spl_autoload_register(static function (string $c) use ($loader): void {
    if (!str_contains($c, '\\Transform\\Include') && !str_ends_with($c, 'FilesystemIncludeResolver')) {
        $loader->loadClass($c);
    }
});
EOF
  old_php() { REAL_AUTOLOAD="$CARVE_PHP_AUTOLOAD" CARVE_PHP_AUTOLOAD="$WORK/old-autoload.php" php "$LIB/render.php" "$@"; }
  old_php "$INC/doc/nested.crv" > "$WORK/old.php" 2> "$WORK/old.php.err"
  has   "old carve-php: directives reported literal" "$WORK/old.php.err" "include directives left literal"
  has   "old carve-php: still renders"        "$WORK/old.php" "{{ sub/a.crv }}"
  if old_php --include-root "$INC" "$INC/doc/nested.crv" >/dev/null 2>&1; then
    bad "old carve-php: explicit root is fatal"
  else ok "old carve-php: explicit root is fatal"; fi
else
  echo "  skip - old carve-php rows need CARVE_PHP_AUTOLOAD"
fi
if [ -n "${CARVE_JS:-}" ] && [[ " ${backends[*]} " == *" js "* ]]; then
  if [ -d "$CARVE_JS" ]; then jsdist="$CARVE_JS/dist"; else jsdist="$(dirname "$CARVE_JS")"; fi
  mkdir -p "$WORK/oldjs"
  for f in "$jsdist"/*; do [ "$(basename "$f")" = node.js ] || ln -s "$f" "$WORK/oldjs/"; done
  old_js() { CARVE_JS="$WORK/oldjs/index.js" node "$LIB/render.mjs" "$@"; }
  old_js "$INC/doc/nested.crv" > "$WORK/old.js" 2> "$WORK/old.js.err"
  has   "old carve-js: directives reported literal" "$WORK/old.js.err" "include directives left literal"
  has   "old carve-js: still renders"         "$WORK/old.js" "{{ sub/a.crv }}"
  if old_js --include-root "$INC" "$INC/doc/nested.crv" >/dev/null 2>&1; then
    bad "old carve-js: explicit root is fatal"
  else ok "old carve-js: explicit root is fatal"; fi
else
  echo "  skip - old carve-js rows need CARVE_JS"
fi

echo "== includes: crv2pdf front end =="
CARVE_RENDERER="${backends[0]}" "$HERE/crv2pdf.sh" --md --include-root "$INC" "$INC/doc/escape.crv" "$WORK/front.md" >/dev/null 2>&1
has   "crv2pdf passes --include-root"         "$WORK/front.md" "SECRET-OUTSIDE"
(cd "$INC" && CARVE_RENDERER="${backends[0]}" "$HERE/crv2pdf.sh" --md --include-root=. doc/escape.crv "$WORK/front-rel.md") >/dev/null 2>&1
has   "crv2pdf resolves a relative root against the cwd" "$WORK/front-rel.md" "SECRET-OUTSIDE"
CARVE_RENDERER="${backends[0]}" "$HERE/crv2pdf.sh" --md --no-includes "$INC/doc/nested.crv" "$WORK/front-off.md" >/dev/null 2>&1
has   "crv2pdf passes --no-includes"          "$WORK/front-off.md" "{{ sub/a.crv }}"

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
