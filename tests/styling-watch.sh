#!/usr/bin/env bash
# A stylesheet outside the document tree must trigger an inotify watch rebuild.
set -uo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="$(mktemp -d)"
mkdir -p "$ROOT/doc" "$ROOT/external" "$ROOT/bin"
printf '# Watch\n' > "$ROOT/doc/input.crv"
printf '.carve h1 { color: red; }\n' > "$ROOT/external/style.css"
cat > "$ROOT/bin/inotifywait" <<'EOF'
#!/usr/bin/env bash
case " $* " in
  *"$MOCK_ROOT/external"*) ;;
  *) echo "external stylesheet directory was not watched" >&2; exit 2 ;;
esac
if [ ! -f "$MOCK_ROOT/triggered" ]; then
  printf '.carve h1 { color: blue; }\n' > "$MOCK_ROOT/external/style.css"
  : > "$MOCK_ROOT/triggered"
  printf '%s\n' "$MOCK_ROOT/external/style.css"
  exit 0
fi
exit 1
EOF
chmod +x "$ROOT/bin/inotifywait"
MOCK_ROOT="$ROOT" PATH="$ROOT/bin:$PATH" "$HERE/crv2pdf.sh" --watch --html \
  --css "$ROOT/external/style.css" "$ROOT/doc/input.crv" "$ROOT/out.html" \
  > "$ROOT/watch.out" 2>&1
if grep -qF 'color: blue;' "$ROOT/out.html" && grep -qF '[rebuild' "$ROOT/watch.out"; then
  echo 'styling watch: ok external CSS triggered a rebuild'
else
  echo 'styling watch: FAIL external CSS did not trigger a rebuild'
  cat "$ROOT/watch.out"
  exit 1
fi
