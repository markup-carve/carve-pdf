#!/usr/bin/env bash
#
# crv2pdf - render Carve (.crv) documents to PDF / HTML / Markdown / text.
#
#   crv2pdf <input.crv> [output] [--pdf|--html|--md|--txt]   single file
#   crv2pdf a.crv b.crv ...        [--out-dir DIR] [--fmt]     batch
#   crv2pdf --watch <input.crv> [output] [--fmt]               rebuild on change
#   crv2pdf --version                                          print the version
#
# Includes ({{ path }} directives) expand against the input's directory:
#   --include-root DIR   containment root to use instead, relative to the cwd
#   --no-includes        leave directives literal
# --watch also rebuilds when an included file changes.
#
# Resources (PDF): images load from the input's directory (or --include-root)
# only; anything else is blocked and reported.
#   --allow-remote       also fetch http(s) images (size- and time-bounded)
#   --link-base URL      resolve relative links against URL; without it they stay
#                        relative in --html and print as plain text in a PDF
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
#   CARVE_RENDERER      js | php | auto (default auto: js if it resolves an engine, else php)
#   CARVE_PHP_AUTOLOAD  composer autoloader providing MarkupCarve\Carve (php backend)
#   CARVE_JS            carve-js checkout or dist/index.js (js backend)
#   CARVE_KATEX         KaTeX dist/ dir for math typesetting (default: autodetect)
#   CARVE_SMART_LOCALE  smart-quotes locale (default: en)
#   CARVE_PDF_FOOTER    host footer template with {page}/{pages}; overrides theme
#                       and document values. Empty disables the footer
#   CHROME_BIN          Chrome/Chromium binary (default: autodetect)
set -euo pipefail

# The one place carve-pdf's version is written. `crv2pdf.sh` is the only file
# `make install` puts on PATH, and the repo has no manifest to hold it instead.
# tests/test.sh asserts this against the newest released CHANGELOG heading, so
# a tag cut from the changelog cannot disagree with what --version prints.
CRV2PDF_VERSION="0.1.6"

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
INCLUDE_ROOT=""
INC_ARGS=()
PRINT_ARGS=()
WRAP_ARGS=()
CSS_FILES=()
THEME=""
POS=()
usage() { echo "usage: crv2pdf <input.crv> [output] [--pdf|--html|--md|--txt] [--css FILE]... [--theme NAME|DIR] [--watch] [--out-dir DIR] [--include-root DIR] [--no-includes] [--allow-remote] [--link-base URL] [--version]" >&2; exit 2; }
need_value() {  # need_value <flag> <remaining args...>
  [ $# -ge 2 ] || { echo "crv2pdf: $1 needs a value" >&2; usage; }
}
while [ $# -gt 0 ]; do
  case "$1" in
    --version|-V) echo "crv2pdf $CRV2PDF_VERSION"; exit 0 ;;
    --pdf|--html|--md|--txt) FORMAT="${1#--}" ;;
    --format=*) FORMAT="${1#--format=}" ;;
    --format) need_value "$@"; FORMAT="$2"; shift ;;
    --watch|-w) WATCH=1 ;;
    --out-dir) need_value "$@"; OUT_DIR="$2"; shift ;;
    --out-dir=*) OUT_DIR="${1#--out-dir=}" ;;
    --include-root) need_value "$@"; INCLUDE_ROOT="$2"; INC_ARGS+=(--include-root "$2"); shift ;;
    --include-root=*) INCLUDE_ROOT="${1#--include-root=}"; INC_ARGS+=(--include-root "$INCLUDE_ROOT") ;;
    --no-includes) INC_ARGS+=(--no-includes) ;;
    --allow-remote) PRINT_ARGS+=(--allow-remote) ;;
    --css) need_value "$@"; CSS_FILES+=("$2"); shift ;;
    --css=*) CSS_FILES+=("${1#--css=}") ;;
    --theme) need_value "$@"; THEME="$2"; shift ;;
    --theme=*) THEME="${1#--theme=}" ;;
    --link-base) need_value "$@"; WRAP_ARGS+=(--link-base "$2"); shift ;;
    --link-base=*) WRAP_ARGS+=(--link-base "${1#--link-base=}") ;;
    --) shift; POS+=("$@"); break ;;
    # An unknown flag used to become the output path (`--bogus` wrote a PDF named --bogus).
    -?*) echo "crv2pdf: unknown option: $1" >&2; usage ;;
    *) POS+=("$1") ;;
  esac
  shift
done

case "$FORMAT" in
  pdf|html|md|txt) ;;
  *) echo "crv2pdf: unknown format: $FORMAT (want pdf, html, md or txt)" >&2; usage ;;
esac
[ ${#POS[@]} -ge 1 ] || usage

# Resolve trusted styles once so a typo fails before any output is written.
for i in "${!CSS_FILES[@]}"; do
  [ -f "${CSS_FILES[$i]}" ] && [ -r "${CSS_FILES[$i]}" ] || { echo "crv2pdf: stylesheet not readable: ${CSS_FILES[$i]}" >&2; exit 2; }
  CSS_FILES[$i]="$(realpath "${CSS_FILES[$i]}")"
done
THEME_CSS="$THEMES/base.css"
THEME_CONFIG=""
if [ -n "$THEME" ]; then
  if [[ "$THEME" != */* ]] && [ -d "$THEMES/$THEME" ]; then theme_dir="$THEMES/$THEME"
  elif [ -d "$THEME" ]; then theme_dir="$THEME"
  else echo "crv2pdf: theme not found: $THEME" >&2; exit 2; fi
  [ -r "$theme_dir/theme.css" ] && [ -r "$theme_dir/theme.json" ] || { echo "crv2pdf: theme needs theme.css and theme.json: $theme_dir" >&2; exit 2; }
  THEME_CSS="$(realpath "$theme_dir/theme.css")"
  THEME_CONFIG="$(realpath "$theme_dir/theme.json")"
fi

# Fail before rendering, with the fix named, rather than mid-pipeline.
if [ "$FORMAT" = "html" ] || [ "$FORMAT" = "pdf" ]; then
  if ! command -v python3 >/dev/null 2>&1; then
    echo "crv2pdf: --$FORMAT needs python3, which is not on PATH (--md and --txt work without it)" >&2
    exit 1
  fi
  if [ "$FORMAT" = "pdf" ] && ! python3 -c 'import websocket' 2>/dev/null; then
    echo "crv2pdf: --pdf needs the websocket-client Python package: pip install websocket-client" >&2
    exit 1
  fi
fi

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

if [ "$BATCH" = "0" ] && [ "$WATCH" = "0" ] && [ ${#POS[@]} -gt 2 ]; then
  echo "crv2pdf: too many arguments: one input and an optional output (several inputs must all be .crv)" >&2
  usage
fi

# --- pick a renderer backend ------------------------------------------------
# `auto` asks each backend whether it can actually resolve its Carve engine,
# rather than trusting that an interpreter on PATH means a working backend. A
# machine with php installed but no MarkupCarve\Carve autoloader used to be sent
# to the php backend and fail there, even with a working node engine present.
# An explicit CARVE_RENDERER is honored as given, so asking for a backend
# reports that backend's own error instead of quietly using the other one.
# With Carve 0.2, js comes first.
RENDERER="${CARVE_RENDERER:-auto}"
if [ "$RENDERER" = "auto" ]; then
  if command -v node >/dev/null 2>&1 && node "$LIB/render.mjs" --probe >/dev/null 2>&1; then
    RENDERER="js"
  elif command -v php >/dev/null 2>&1 && php "$LIB/render.php" --probe >/dev/null 2>&1; then
    RENDERER="php"
  else
    {
      echo "crv2pdf: no usable Carve renderer backend."
      if command -v php >/dev/null 2>&1; then
        echo "  php:  on PATH, but no autoloader provides MarkupCarve\\Carve"
      else
        echo "  php:  not on PATH"
      fi
      if command -v node >/dev/null 2>&1; then
        echo "  node: on PATH, but the @markup-carve/carve package was not found"
      else
        echo "  node: not on PATH"
      fi
      echo "Install one engine here, or anywhere the matching variable can point:"
      echo "  composer require markup-carve/carve-php   # CARVE_PHP_AUTOLOAD=.../vendor/autoload.php"
      echo "  npm install @markup-carve/carve           # CARVE_JS=.../dist/index.js"
    } >&2
    exit 1
  fi
fi

WORK="$(mktemp -d "${TMPDIR:-/tmp}/crv2pdf.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

render_meta() {  # render_meta <in> -> the engine's frontmatter block on stdout
  case "$RENDERER" in
    php) php "$LIB/render.php" --meta "$1" ;;
    js)  node "$LIB/render.mjs" --meta "$1" ;;
  esac
}

render() {  # render() <in> <format> -> writes $WORK/frag and $WORK/deps
  case "$RENDERER" in
    php) php "$LIB/render.php" --format "$2" --deps "$WORK/deps" ${INC_ARGS[@]+"${INC_ARGS[@]}"} "$1" > "$WORK/frag" ;;
    js)  node "$LIB/render.mjs" --format "$2" --deps "$WORK/deps" ${INC_ARGS[@]+"${INC_ARGS[@]}"} "$1" > "$WORK/frag" ;;
    *)   echo "crv2pdf: unknown CARVE_RENDERER '$RENDERER' (want php|js|auto)" >&2; exit 2 ;;
  esac
}

build_one() {  # build_one <input.crv> <output>
  local in="$1" out="$2"
  if [ ! -f "$in" ]; then echo "crv2pdf: input not found: $in" >&2; return 1; fi
  if [ ! -r "$in" ]; then echo "crv2pdf: cannot read input: $in" >&2; return 1; fi
  if [ ! -d "$(dirname "$out")" ]; then echo "crv2pdf: output directory does not exist: $(dirname "$out")" >&2; return 1; fi

  # Every step returns explicitly: batch mode calls this as `build_one ... || rc=1`,
  # and a function called in an `||` list runs with `set -e` switched off.
  if [ "$FORMAT" = "md" ] || [ "$FORMAT" = "txt" ]; then
    render "$in" "$FORMAT" || return 1
    cp "$WORK/frag" "$out" || return 1
    echo "$out ($RENDERER backend, $FORMAT)"
    return 0
  fi

  render "$in" html || return 1
  # An engine without --meta leaves the file empty; meta.py then finds the block itself.
  render_meta "$in" > "$WORK/fm.json" 2>/dev/null || : > "$WORK/fm.json"
  python3 "$LIB/meta.py" "$in" "$WORK/fm.json" > "$WORK/meta.json" || return 1
  local srcdir; srcdir="$(cd "$(dirname "$in")" && pwd)"
  local project_root="$srcdir"
  [ -z "$INCLUDE_ROOT" ] || project_root="$(realpath "$INCLUDE_ROOT")"
  local project_css="$project_root/carve-pdf.css"
  local custom=()
  [ ! -f "$project_css" ] || [ -r "$project_css" ] || { echo "crv2pdf: project stylesheet not readable: $project_css" >&2; return 1; }
  [ ! -f "$project_css" ] || custom+=(--custom-css "$project_css")
  for cssfile in "${CSS_FILES[@]}"; do custom+=(--custom-css "$cssfile"); done
  local mode=(); [ "$FORMAT" = "pdf" ] && mode=(--print)
  local asset_base=(); [ "$FORMAT" != "html" ] || asset_base=(--asset-base "$out")
  local theme_args=(); [ -z "$THEME_CONFIG" ] || theme_args=(--theme-config "$THEME_CONFIG")
  python3 "$LIB/wrap.py" ${mode[@]+"${mode[@]}"} ${WRAP_ARGS[@]+"${WRAP_ARGS[@]}"} \
    --footer-out "$WORK/footer" --header-out "$WORK/header" --css-deps-out "$WORK/css-deps" \
    ${asset_base[@]+"${asset_base[@]}"} ${theme_args[@]+"${theme_args[@]}"} ${custom[@]+"${custom[@]}"} \
    "$WORK/frag" "$WORK/meta.json" "$srcdir" "$WORK/doc.html" \
    "$THEMES/carve-css/tokens.css" "$THEMES/carve-css/core.css" \
    "$THEMES/carve-css/extensions.css" "$THEMES/carve-css/recipes.css" \
    "$THEME_CSS" "$THEMES/print.css" >/dev/null || return 1

  if [ "$FORMAT" = "html" ]; then
    cp "$WORK/doc.html" "$out" || return 1
    echo "$out ($RENDERER backend, html)"
    return 0
  fi

  # Images may come from the input's directory, or the include root when one is set.
  local allow=(--allow-dir "$srcdir")
  if [ -n "$INCLUDE_ROOT" ]; then allow+=(--allow-dir "$INCLUDE_ROOT"); fi
  allow+=(--allow-dir "$(dirname "$THEME_CSS")")
  [ ! -f "$project_css" ] || allow+=(--allow-dir "$project_root")
  for cssfile in "${CSS_FILES[@]}"; do allow+=(--allow-dir "$(dirname "$cssfile")"); done
  while IFS= read -r cssdep; do
    [ -z "$cssdep" ] || allow+=(--allow-dir "$(dirname "$cssdep")")
  done < "$WORK/css-deps"
  allow+=(${PRINT_ARGS[@]+"${PRINT_ARGS[@]}"})
  local author; author="$(python3 -c 'import json,sys; a=json.load(open(sys.argv[1])).get("author"); print(", ".join(map(str,a)) if isinstance(a,list) else (a or ""))' "$WORK/meta.json")"
  if [ -n "$author" ]; then allow+=(--author "$author"); fi

  local footer; footer="$(cat "$WORK/footer")"
  local header; header="$(cat "$WORK/header")"
  python3 "$LIB/print_cdp.py" "$WORK/doc.html" "$out" "$footer" --header "$header" --css-margins "${allow[@]}" >/dev/null || return 1
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
  # The renderers resolve includes from the input's real path, so watch that.
  in_real="$(readlink -f "$IN" 2>/dev/null || echo "$IN")"
  dir="$(cd "$(dirname "$in_real")" && pwd -P)"; base="$(basename "$in_real")"
  # Dependencies are written relative to the include root.
  root="$dir"
  if [ -n "$INCLUDE_ROOT" ]; then root="$(cd "$INCLUDE_ROOT" 2>/dev/null && pwd -P || echo "$dir")"; fi

  watched_files() {  # the input plus every file the last render read
    echo "$dir/$base"
    [ -f "$WORK/deps" ] && while IFS= read -r d; do echo "$root/$d"; done < "$WORK/deps"
    echo "$THEME_CSS"
    [ -z "$THEME_CONFIG" ] || echo "$THEME_CONFIG"
    echo "$root/carve-pdf.css"
    for cssfile in "${CSS_FILES[@]}"; do echo "$cssfile"; done
    [ ! -f "$WORK/css-deps" ] || cat "$WORK/css-deps"
    return 0
  }

  mtime() {  # nanosecond precision where available; include size for quick saves
    stat -c '%y:%s' "$1" 2>/dev/null || stat -f '%m:%z' "$1" 2>/dev/null || echo 0
  }
  signature() { watched_files | while IFS= read -r f; do echo "$f $(mtime "$f")"; done; }

  rebuild_until_stable() {
    local before after
    before="$(signature)"
    while true; do
      echo "[rebuild $(date +%T)]"
      build_one "$IN" "$OUT" || true
      after="$(signature)"
      last_sig="$after"
      [ "$after" = "$before" ] && break
      before="$after"
    done
  }

  if command -v inotifywait >/dev/null 2>&1; then
    # Rebuild the watch set after every event so newly imported CSS is watched.
    last_sig="$(signature)"
    while true; do
      if [ "$(signature)" != "$last_sig" ]; then
        rebuild_until_stable
        continue
      fi
      mapfile -t watch_dirs < <(
        { echo "$dir"; echo "$root"; watched_files | while IFS= read -r file; do dirname "$file"; done; } |
          while IFS= read -r candidate; do [ ! -d "$candidate" ] || realpath "$candidate"; done | sort -u
      )
      if f="$(inotifywait -t 1 -q -e close_write,moved_to,create,delete,moved_from --format '%w%f' "${watch_dirs[@]}")"; then
        :
      elif [ "$?" -eq 2 ]; then
        continue
      else
        echo "crv2pdf: file watcher stopped" >&2
        break
      fi
      if watched_files | grep -qxF -- "$f"; then
        rebuild_until_stable
      fi
    done
  else
    # portable fallback: 1s mtime poll
    last="$(signature)"
    while true; do
      sleep 1
      now="$(signature)"
      if [ "$now" != "$last" ]; then
        echo "[rebuild $(date +%T)]"; build_one "$IN" "$OUT" || true
        last="$(signature)"
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
