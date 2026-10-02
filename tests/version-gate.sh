#!/usr/bin/env bash
#
# Refuse a tag whose name disagrees with either place the version is written.
#
# The tag is the leg nothing else can see: tests/test.sh compares `--version`
# against the newest released CHANGELOG heading, but neither of them knows what
# a tag was cut as, so a tag from the wrong commit passes every existing check.
#
# Usage: tests/version-gate.sh <tag>   (a leading v is accepted)
set -uo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"

tag="${1-}"
if [ -z "$tag" ]; then
  echo "version-gate: usage: tests/version-gate.sh <tag>" >&2
  exit 2
fi

want="${tag#v}"

script="$(sed -n 's/^CRV2PDF_VERSION="\([^"]*\)".*/\1/p' "$HERE/crv2pdf.sh" | head -1)"
printed="$("$HERE/crv2pdf.sh" --version 2>/dev/null)"
printed="${printed#crv2pdf }"
changelog="$(grep -m1 -oE '^## \[[0-9]+\.[0-9]+\.[0-9]+\]' "$HERE/CHANGELOG.md" | tr -d '#[] ')"

echo "tag:              $tag"
echo "CRV2PDF_VERSION:  ${script:-(not found)}"
echo "--version prints: ${printed:-(nothing)}"
echo "CHANGELOG:        ${changelog:-(no released heading)}"

bad=0
note() { echo "version-gate: $1" >&2; bad=1; }

# Report every disagreement rather than the first, so one run tells the
# operator which of the three to move.
case "$want" in
  [0-9]*.[0-9]*.[0-9]*) ;;
  *) note "tag '$tag' is not x.y.z" ;;
esac
[ -n "$script" ]    || note "crv2pdf.sh has no CRV2PDF_VERSION assignment"
[ -n "$changelog" ] || note "CHANGELOG.md has no released version heading"
[ "$script" = "$want" ]    || note "tag says $want, CRV2PDF_VERSION says ${script:-nothing}"
[ "$printed" = "$want" ]   || note "tag says $want, --version prints ${printed:-nothing}"
[ "$changelog" = "$want" ] || note "tag says $want, newest CHANGELOG heading is ${changelog:-nothing}"

if [ "$bad" -ne 0 ]; then
  echo "version-gate: REFUSED" >&2
  exit 1
fi
echo "version-gate: $want agrees across the tag, crv2pdf.sh and CHANGELOG.md"
