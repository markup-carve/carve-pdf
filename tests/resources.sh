#!/usr/bin/env bash
#
# Resource containment gate.
#
# A document may load images from its own directory and nothing else: not a
# sibling directory, not an absolute path, not a symlink that leads out, and no
# remote URL unless --allow-remote is given. Relative links and the --html output
# must not carry the build machine's paths either.
#
# Counts embedded images with pdfimages, so each case is its own one-image
# document. Skips (and says so) without Chrome, websocket-client or poppler.
set -uo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"
SERVER_PID=""
cleanup() { [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null; rm -rf "$WORK"; }
trap cleanup EXIT

pass=0; fail=0; skip=0
ok()   { echo "  ok   - $1"; pass=$((pass+1)); }
bad()  { echo "  FAIL - $1"; fail=$((fail+1)); }
skipd(){ echo "  skip - $1"; skip=$((skip+1)); }
has()  { if grep -qF -- "$3" "$2"; then ok "$1"; else bad "$1 (missing: $3)"; fi; }
hasnt(){ if grep -qF -- "$3" "$2"; then bad "$1 (unexpected: $3)"; else ok "$1"; fi; }

have_chrome() {
  [ -n "${CHROME_BIN:-}" ] && command -v "$CHROME_BIN" >/dev/null 2>&1 && return 0
  command -v google-chrome >/dev/null 2>&1 || command -v chromium >/dev/null 2>&1 \
    || command -v chromium-browser >/dev/null 2>&1
}

png() {  # png <path>: a valid 2x2 PNG
  python3 - "$1" <<'PY'
import struct, sys, zlib
def chunk(t, d):
    return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
raw = b"".join(b"\x00" + b"\xff\x00\x00" * 2 for _ in range(2))
data = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
open(sys.argv[1], "wb").write(data)
PY
}

DOC="$WORK/doc"
mkdir -p "$DOC/img" "$WORK/secret"
png "$DOC/img/ok.png"
png "$WORK/secret/secret.png"
ln -s ../../secret/secret.png "$DOC/img/link.png"

printf '# OK\n\n![ok](img/ok.png)\n' > "$DOC/ok.crv"
printf '# Traversal\n\n![trav](../secret/secret.png)\n' > "$DOC/trav.crv"
printf '# Absolute\n\n![abs](%s)\n' "$WORK/secret/secret.png" > "$DOC/abs.crv"
printf '# Symlink\n\n![link](img/link.png)\n' > "$DOC/symlink.crv"
printf '# Links\n\nSee [chapter two](chapter2.crv), [root](/etc/passwd) and [top](#links).\n' > "$DOC/links.crv"

images() {  # images <pdf>: embedded 2x2 test images (Chrome's broken-image icon is not one)
  pdfimages -list "$1" 2>/dev/null | awk 'NR > 2 && $3 == "image" && $4 == 2 && $5 == 2' | grep -c . || true
}

echo "== resources: --html output carries no host paths =="
"$HERE/crv2pdf.sh" --html "$DOC/links.crv" "$WORK/links.html" >/dev/null 2>&1
hasnt "--html has no <base>"                 "$WORK/links.html" "<base"
hasnt "--html names no build directory"      "$WORK/links.html" "$WORK"
has   "a relative link stays relative"       "$WORK/links.html" 'href="chapter2.crv"'
"$HERE/crv2pdf.sh" --html --link-base https://example.org/docs/ "$DOC/links.crv" "$WORK/links-base.html" >/dev/null 2>&1
has   "--link-base resolves a relative link" "$WORK/links-base.html" 'href="https://example.org/docs/chapter2.crv"'
has   "--link-base leaves a fragment alone"  "$WORK/links-base.html" 'href="#links"'
"$HERE/crv2pdf.sh" --html "$DOC/ok.crv" "$WORK/ok.html" >/dev/null 2>&1
has   "an image src stays relative in --html" "$WORK/ok.html" 'src="img/ok.png"'

echo "== resources: printed PDF =="
if ! have_chrome; then
  skipd "no Chrome binary - resource containment is UNMEASURED"
elif ! python3 -c 'import websocket' 2>/dev/null; then
  skipd "no websocket-client - resource containment is UNMEASURED"
elif ! command -v pdfimages >/dev/null 2>&1; then
  skipd "no pdfimages (poppler-utils) - resource containment is UNMEASURED"
else
  "$HERE/crv2pdf.sh" "$DOC/ok.crv" "$WORK/ok.pdf" > "$WORK/ok.out" 2>&1
  if [ "$(images "$WORK/ok.pdf")" = "1" ]; then ok "an image beside the document is embedded"
  else bad "an image beside the document is embedded (saw $(images "$WORK/ok.pdf"); $(tr '\n' ' ' < "$WORK/ok.out"))"; fi

  for case in trav abs symlink; do
    "$HERE/crv2pdf.sh" "$DOC/$case.crv" "$WORK/$case.pdf" > "$WORK/$case.out" 2>&1
    if [ ! -s "$WORK/$case.pdf" ]; then bad "$case: the document still prints"
    elif [ "$(images "$WORK/$case.pdf")" = "0" ]; then ok "$case: an image outside the document directory is refused"
    else bad "$case: an image outside the document directory is refused"; fi
    has "$case: the refusal is reported" "$WORK/$case.out" "blocked"
  done

  "$HERE/crv2pdf.sh" "$DOC/links.crv" "$WORK/links.pdf" >/dev/null 2>&1
  if grep -aq "file:" "$WORK/links.pdf"; then bad "the PDF carries no file: link"
  else ok "the PDF carries no file: link"; fi

  # A local server stands in for a remote host and records what it was asked for.
  python3 - "$WORK/srv" "$DOC/img/ok.png" > "$WORK/server.log" 2>&1 <<'PY' &
import http.server, os, socketserver, sys, time
root, image = sys.argv[1], sys.argv[2]
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        sys.stdout.write(self.path + "\n"); sys.stdout.flush()
        if self.path.startswith("/slow"):
            time.sleep(30)
        body = open(image, "rb").read()
        if self.path.startswith("/big"):
            body = body + b"\0" * (3 * 1024 * 1024)
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a):
        pass
class S(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
s = S(("127.0.0.1", 0), H)
open(root + ".port", "w").write(str(s.server_address[1]))
s.serve_forever()
PY
  SERVER_PID=$!
  for _ in $(seq 1 50); do [ -s "$WORK/srv.port" ] && break; sleep 0.1; done
  PORT="$(cat "$WORK/srv.port" 2>/dev/null)"
  if [ -z "$PORT" ]; then
    bad "local test server started"
  else
    printf '# Remote\n\n![remote](http://127.0.0.1:%s/pixel.png)\n\n[x]{style="background-image:url(http://127.0.0.1:%s/style.png)"}\n' "$PORT" "$PORT" > "$DOC/remote.crv"
    printf '# Slow\n\n![slow](http://127.0.0.1:%s/slow.png)\n' "$PORT" > "$DOC/slow.crv"
    printf '# Big\n\n![big](http://127.0.0.1:%s/big.png)\n' "$PORT" > "$DOC/big.crv"

    "$HERE/crv2pdf.sh" "$DOC/remote.crv" "$WORK/remote.pdf" > "$WORK/remote.out" 2>&1
    if [ -s "$WORK/server.log" ]; then bad "a remote image is not fetched by default (server saw: $(tr '\n' ' ' < "$WORK/server.log"))"
    else ok "a remote image is not fetched by default"; fi
    if [ "$(images "$WORK/remote.pdf")" = "0" ]; then ok "a remote image is not embedded by default"
    else bad "a remote image is not embedded by default"; fi

    "$HERE/crv2pdf.sh" --allow-remote "$DOC/remote.crv" "$WORK/remote-on.pdf" > "$WORK/remote-on.out" 2>&1
    has "--allow-remote fetches the image" "$WORK/server.log" "/pixel.png"
    if [ "$(images "$WORK/remote-on.pdf")" -ge 1 ]; then ok "--allow-remote embeds the image"
    else bad "--allow-remote embeds the image ($(tr '\n' ' ' < "$WORK/remote-on.out"))"; fi

    start=$(date +%s)
    CARVE_PDF_REMOTE_TIMEOUT=2 "$HERE/crv2pdf.sh" --allow-remote "$DOC/slow.crv" "$WORK/slow.pdf" > "$WORK/slow.out" 2>&1
    took=$(( $(date +%s) - start ))
    if [ -s "$WORK/slow.pdf" ] && [ "$took" -lt 20 ]; then ok "a remote server that does not answer is given up on (${took}s)"
    else bad "a remote server that does not answer is given up on (${took}s)"; fi

    CARVE_PDF_REMOTE_MAX_BYTES=1048576 "$HERE/crv2pdf.sh" --allow-remote "$DOC/big.crv" "$WORK/big.pdf" > "$WORK/big.out" 2>&1
    if [ -s "$WORK/big.pdf" ] && [ "$(images "$WORK/big.pdf")" = "0" ]; then ok "a remote image over the size limit is refused"
    else bad "a remote image over the size limit is refused"; fi
    has "the size refusal is reported" "$WORK/big.out" "limit"
  fi
fi

echo "resources: passed $pass, failed $fail, skipped $skip"
[ "$fail" -eq 0 ]
