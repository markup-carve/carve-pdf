#!/usr/bin/env bash
#
# Printed-content gate.
#
# Paper cannot scroll, so a wide table or an unbreakable word that runs past the
# page edge is simply gone. This gate prints such content and reads the text
# back with pdftotext. It also checks the list delimiter an author wrote, the
# PDF outline and the author metadata. Skips (and says so) without Chrome,
# websocket-client or poppler.
set -uo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

pass=0; fail=0; skip=0
ok()   { echo "  ok   - $1"; pass=$((pass+1)); }
bad()  { echo "  FAIL - $1"; fail=$((fail+1)); }
skipd(){ echo "  skip - $1"; skip=$((skip+1)); }

have_chrome() {
  [ -n "${CHROME_BIN:-}" ] && command -v "$CHROME_BIN" >/dev/null 2>&1 && return 0
  command -v google-chrome >/dev/null 2>&1 || command -v chromium >/dev/null 2>&1 \
    || command -v chromium-browser >/dev/null 2>&1
}

echo "== print content =="
if ! have_chrome; then
  skipd "no Chrome binary - printed content is UNMEASURED"
elif ! python3 -c 'import websocket' 2>/dev/null; then
  skipd "no websocket-client - printed content is UNMEASURED"
elif ! command -v pdftotext >/dev/null 2>&1 || ! command -v pdfinfo >/dev/null 2>&1; then
  skipd "no pdftotext/pdfinfo (poppler-utils) - printed content is UNMEASURED"
else
  word="WORDSTART$(printf 'x%.0s' $(seq 1 300))WORDEND"
  {
    printf -- '---\ntitle: Content\nauthor: Ada Lövelace\n---\n\n# Content\n\n'
    printf '%s\n\n' "$word"
    printf 'Inline `CODESTART%sCODEEND` here.\n\n' "$(printf 'y%.0s' $(seq 1 150))"
    head="" ; row=""
    for i in $(seq 0 13); do head="$head|= Header$i "; row="$row| value-$i-abcdefgh "; done
    printf '%s|\n%s|\n\n' "$head" "$row"
    printf '## Lists\n\n1) first\n2) second\n\nx\n\na) alpha\nb) beta\n\ny\n\nA) upper\nB) next\n'
  } > "$WORK/content.crv"

  "$HERE/crv2pdf.sh" "$WORK/content.crv" "$WORK/content.pdf" > "$WORK/content.out" 2>&1
  if [ ! -s "$WORK/content.pdf" ]; then
    bad "the content fixture prints ($(tr '\n' ' ' < "$WORK/content.out"))"
  else
    pdftotext -layout "$WORK/content.pdf" "$WORK/content.txt"
    flat="$(tr -d ' \n\r\f' < "$WORK/content.txt")"
    case "$flat" in *"$word"*) ok "a 300-character word survives in full" ;;
      *) bad "a 300-character word survives in full (x's printed: $(tr -cd 'x' <<< "$flat" | wc -c))" ;; esac
    case "$flat" in *CODEEND*) ok "a long inline code span survives" ;; *) bad "a long inline code span survives" ;; esac
    # A narrow cell wraps mid-word, so read the table back in drawing order.
    raw="$(pdftotext -raw "$WORK/content.pdf" - | tr -d ' \n\r\f')"
    case "$raw" in *Header13*) ok "the last column of a 14-column table survives" ;; *) bad "the last column of a 14-column table survives" ;; esac
    case "$raw" in *value-13-abcdefgh*) ok "the last cell of a 14-column table survives" ;; *) bad "the last cell of a 14-column table survives" ;; esac
    if grep -qE '^\s*1\)\s+first' "$WORK/content.txt"; then ok "a 1) list prints its ) delimiter"
    else bad "a 1) list prints its ) delimiter ($(grep -m1 first "$WORK/content.txt"))"; fi
    if grep -qE '^\s*a\)\s+alpha' "$WORK/content.txt"; then ok "an a) list prints its ) delimiter"
    else bad "an a) list prints its ) delimiter ($(grep -m1 alpha "$WORK/content.txt"))"; fi
    if grep -qE '^\s*A\)\s+upper' "$WORK/content.txt"; then ok "an A) list prints upper-case letters and its ) delimiter"
    else bad "an A) list prints upper-case letters and its ) delimiter ($(grep -m1 upper "$WORK/content.txt"))"; fi
    if grep -aq '/Outlines' "$WORK/content.pdf"; then ok "the PDF carries a heading outline"
    else bad "the PDF carries a heading outline"; fi
    author="$(pdfinfo "$WORK/content.pdf" 2>/dev/null | sed -n 's/^Author: *//p')"
    if [ "$author" = "Ada Lövelace" ]; then ok "frontmatter author is the PDF author"
    else bad "frontmatter author is the PDF author (got '$author')"; fi
    title="$(pdfinfo "$WORK/content.pdf" 2>/dev/null | sed -n 's/^Title: *//p')"
    if [ "$title" = "Content" ]; then ok "the PDF title survives the metadata update"
    else bad "the PDF title survives the metadata update (got '$title')"; fi
  fi
fi

echo "print content: passed $pass, failed $fail, skipped $skip"
[ "$fail" -eq 0 ]
