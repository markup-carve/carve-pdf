#!/usr/bin/env python3
"""Render an HTML file to PDF via Chrome DevTools Page.printToPDF.

Why CDP instead of `chrome --print-to-pdf`: the CLI flag can't set a custom
footer (page numbers), and Blink ignores CSS `@bottom-center` counters. CDP
gives footerTemplate + printBackground (keeps admonition colors).

Usage: print_cdp.py <input.html> <output.pdf> [footer-template]
                    [--allow-dir DIR]... [--allow-remote]

The footer template is plain text with two placeholders, {page} and {pages}
(e.g. "Page {page} of {pages}" or "Seite {page} von {pages}"). Precedence:
argv[3], then $CARVE_PDF_FOOTER, then the English default. An empty template
disables the footer entirely.

Every request the page makes is intercepted. Allowed: the input file, data:
and blob: URLs, and files whose real path lies under an --allow-dir. Remote
http(s) is refused unless --allow-remote is given; then this script fetches it
itself, bounded by $CARVE_PDF_REMOTE_TIMEOUT seconds and
$CARVE_PDF_REMOTE_MAX_BYTES bytes per resource.
"""
import base64
import html
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

try:
    import websocket  # websocket-client (synchronous)
except ImportError:
    sys.exit("print_cdp.py: needs the websocket-client package: pip install websocket-client")

USAGE = "usage: print_cdp.py <input.html> <output.pdf> [footer-template] [--allow-dir DIR]... [--allow-remote]"
positional = []
ALLOW_DIRS = []
ALLOW_REMOTE = False
_argv = sys.argv[1:]
while _argv:
    _arg = _argv.pop(0)
    if _arg == "--allow-remote":
        ALLOW_REMOTE = True
    elif _arg == "--allow-dir":
        if not _argv:
            sys.exit(USAGE)
        ALLOW_DIRS.append(Path(_argv.pop(0)).resolve())
    else:
        positional.append(_arg)
if len(positional) < 2:
    sys.exit(USAGE)

HTML = Path(positional[0]).resolve()
PDF = Path(positional[1]).resolve()
if not HTML.is_file():
    sys.exit(f"print_cdp.py: input not found: {HTML}")

# Footer template: argv[3] > $CARVE_PDF_FOOTER > English default. Empty -> no footer.
_default_footer = "Page {page} of {pages}"
if len(positional) >= 3:
    footer_tpl = positional[2]
else:
    footer_tpl = os.environ.get("CARVE_PDF_FOOTER", _default_footer)

REMOTE_TIMEOUT = float(os.environ.get("CARVE_PDF_REMOTE_TIMEOUT") or 10)
REMOTE_MAX_BYTES = int(os.environ.get("CARVE_PDF_REMOTE_MAX_BYTES") or 10 * 1024 * 1024)


def build_footer(tpl: str) -> str:
    if tpl.strip() == "":
        return ""
    body = (
        html.escape(tpl)
        .replace("{page}", '<span class="pageNumber"></span>')
        .replace("{pages}", '<span class="totalPages"></span>')
    )
    return (
        '<div style="font-size:9px;width:100%;text-align:center;color:#8a8a8a;'
        'font-family:sans-serif;padding:0 18mm;">' + body + "</div>"
    )


FOOTER = build_footer(footer_tpl)
DISPLAY_FOOTER = FOOTER != ""
HEADER = "<span></span>"  # empty -> suppresses Chrome's default header


def find_chrome() -> str:
    env = os.environ.get("CHROME_BIN")
    if env and shutil.which(env):
        return env
    for name in (
        "google-chrome", "google-chrome-stable", "chromium",
        "chromium-browser", "chrome",
    ):
        path = shutil.which(name)
        if path:
            return path
    sys.exit("print_cdp.py: no Chrome/Chromium binary found (set $CHROME_BIN)")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# Chrome has to start, open the file: URL and register a page target before the
# DevTools list names it. The old budget was 15s, which is roughly a cold start
# on an idle machine and nothing more: run 37864364196 exceeded it on a loaded
# runner and failed a gate that had nothing to say about the artifact. 90s is
# chosen against the job bound rather than against a measurement, so a slow
# runner waits instead of failing: every CI job here sets timeout-minutes, so
# the job still ends on its own schedule, and a wait this long only happens on
# a machine that would have failed the old budget anyway.
TARGET_WAIT_SECONDS = 90

TRACE = bool(os.environ.get("CARVE_CDP_TRACE"))


def _trace(msg: str) -> None:
    if TRACE:
        print(f"cdp: {msg}", file=sys.stderr, flush=True)


class ChromeGone(RuntimeError):
    """Chrome is not running, so waiting longer cannot help."""


def page_ws(port: int, proc: subprocess.Popen, deadline: float) -> str:
    """Poll the DevTools target list for the page target's websocket URL.

    Bounded retry, not a background loop. The two failure modes are reported
    apart: a Chrome that died cannot list a target however long we wait, while
    a Chrome that is merely slow is given the whole deadline. The old code
    raised one message for both, so a failure never said which had happened.
    """
    started = time.time()
    attempts = 0
    last_seen: list = []
    while True:
        attempts += 1
        rc = proc.poll()
        if rc is not None:
            raise ChromeGone(
                f"Chrome exited with status {rc} after "
                f"{time.time() - started:.1f}s, before listing a page target "
                f"(DevTools port {port}, {attempts} attempt(s)). It is not "
                f"running, so this is not a timeout - check the browser "
                f"binary, its flags and the profile directory."
            )
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/json", timeout=2
            ) as resp:
                targets = json.load(resp)
            last_seen = sorted({t.get("type", "?") for t in targets})
            for t in targets:
                if t.get("type") == "page":
                    _trace(
                        f"page target listed after {time.time() - started:.2f}s "
                        f"({attempts} attempt(s))"
                    )
                    return t["webSocketDebuggerUrl"]
            _trace(
                f"attempt {attempts} at {time.time() - started:.2f}s: "
                f"Chrome is up, no page target yet (types: "
                f"{','.join(last_seen) or 'none'})"
            )
        except Exception as exc:
            _trace(
                f"attempt {attempts} at {time.time() - started:.2f}s: "
                f"DevTools port not answering yet ({type(exc).__name__})"
            )
        if time.time() >= deadline:
            break
        time.sleep(0.15)
    waited = time.time() - started
    raise RuntimeError(
        f"Chrome is running (pid {proc.pid}) but listed no page target "
        f"within {waited:.1f}s over {attempts} attempt(s) on DevTools port "
        f"{port}. Target types last seen: "
        f"{','.join(last_seen) or 'none (port never answered)'}. Chrome did "
        f"not exit, so it started slowly or is wedged rather than crashed; raise "
        f"TARGET_WAIT_SECONDS if a runner needs longer."
    )


def wait_for_page_ws(port: int, proc: subprocess.Popen, tool: str) -> str:
    """page_ws with the standard deadline, reporting failures without a traceback."""
    try:
        return page_ws(port, proc, time.time() + TARGET_WAIT_SECONDS)
    except ChromeGone as exc:
        sys.exit(f"{tool}: Chrome did not stay up: {exc}")
    except RuntimeError as exc:
        sys.exit(f"{tool}: Chrome started but no page target appeared: {exc}")


def _note(msg: str) -> None:
    print(f"print_cdp.py: {msg}", file=sys.stderr, flush=True)


def _short(url: str) -> str:
    return url if len(url) <= 200 else url[:200] + "..."


def file_allowed(url: str) -> bool:
    """The input itself, or a file whose real path is under an allowed dir.

    Resolving symlinks first is what refuses `../`, absolute paths and links
    that lead out, the same containment the include pass applies.
    """
    parts = urllib.parse.urlsplit(url)
    if parts.netloc not in ("", "localhost"):
        return False
    try:
        real = Path(urllib.request.url2pathname(parts.path)).resolve(strict=True)
    except (OSError, RuntimeError):
        return False
    if real == HTML:
        return True
    return real.is_file() and any(real.is_relative_to(d) for d in ALLOW_DIRS)


class _NoRedirectOffWeb(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme not in ("http", "https"):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_NoRedirectOffWeb)


def fetch_remote(url: str):
    """(status, headers, body) or raise; bounded in time and size."""
    req = urllib.request.Request(url, headers={"User-Agent": "carve-pdf"})
    deadline = time.time() + REMOTE_TIMEOUT
    with _opener.open(req, timeout=REMOTE_TIMEOUT) as resp:
        length = resp.headers.get("Content-Length")
        if length and length.isdigit() and int(length) > REMOTE_MAX_BYTES:
            raise ValueError(f"{length} bytes is over the {REMOTE_MAX_BYTES}-byte limit")
        body = b""
        while True:
            if time.time() > deadline:
                raise TimeoutError(f"took longer than {REMOTE_TIMEOUT:g}s")
            chunk = resp.read(65536)
            if not chunk:
                break
            body += chunk
            if len(body) > REMOTE_MAX_BYTES:
                raise ValueError(f"over the {REMOTE_MAX_BYTES}-byte limit")
        headers = [
            {"name": k, "value": v} for k, v in resp.headers.items()
            if k.lower() in ("content-type", "cache-control")
        ]
        return resp.status, headers, body


def chrome_flags() -> list:
    flags = [
        "--headless=new", "--disable-gpu", "--no-first-run",
        "--no-default-browser-check", "--disable-background-networking",
        "--disable-component-update",
    ]
    # Chrome refuses to start as root with its sandbox on, so root (a container)
    # is the one case that drops it. CARVE_CHROME_NO_SANDBOX=1 is the escape
    # hatch for a host whose kernel cannot provide one.
    as_root = hasattr(os, "geteuid") and os.geteuid() == 0
    if as_root or os.environ.get("CARVE_CHROME_NO_SANDBOX") == "1":
        flags.append("--no-sandbox")
    return flags


port = free_port()
profile = tempfile.mkdtemp(prefix="carve-pdf-cdp-")
chrome = subprocess.Popen(
    [
        find_chrome(), *chrome_flags(),
        f"--remote-debugging-port={port}", "--remote-allow-origins=*",
        f"--user-data-dir={profile}", "about:blank",
    ],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)

ws = None
try:
    ws = websocket.create_connection(
        wait_for_page_ws(port, chrome, "print_cdp.py"), max_size=None, timeout=30
    )
    ws.settimeout(30)
    mid = 0
    events = []

    def send(method, params=None):
        global mid
        mid += 1
        ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        return mid

    def on_paused(params):
        rid, url = params["requestId"], params["request"]["url"]
        scheme = urllib.parse.urlsplit(url).scheme.lower()
        if scheme in ("data", "blob") or (scheme == "file" and file_allowed(url)):
            send("Fetch.continueRequest", {"requestId": rid})
            return
        if scheme in ("http", "https") and ALLOW_REMOTE:
            try:
                status, headers, body = fetch_remote(url)
            except Exception as exc:
                _note(f"remote resource not loaded ({exc}): {_short(url)}")
                send("Fetch.failRequest", {"requestId": rid, "errorReason": "Failed"})
                return
            send("Fetch.fulfillRequest", {
                "requestId": rid, "responseCode": status, "responseHeaders": headers,
                "body": base64.b64encode(body).decode("ascii"),
            })
            return
        why = "remote resource (pass --allow-remote to load it)" if scheme in ("http", "https") \
            else "file outside the document directory" if scheme == "file" \
            else f"{scheme}: resource"
        _note(f"blocked {why}: {_short(url)}")
        send("Fetch.failRequest", {"requestId": rid, "errorReason": "BlockedByClient"})

    def recv():
        """The next message that is not an intercepted request."""
        while True:
            msg = json.loads(ws.recv())
            if msg.get("method") == "Fetch.requestPaused":
                on_paused(msg["params"])
                continue
            return msg

    def cmd(method, params=None):
        want = send(method, params)
        while True:
            msg = recv()
            if "method" in msg:
                events.append(msg)
                continue
            if msg.get("id") != want:
                continue  # replies to fire-and-forget Fetch calls
            if "error" in msg:
                raise RuntimeError(f"CDP {method} failed: {msg['error']}")
            return msg.get("result", {})

    # Interception is on before the document is requested, so nothing it
    # references loads unchecked.
    cmd("Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]})
    cmd("Page.enable")
    cmd("Page.navigate", {"url": HTML.as_uri()})

    # Wait for the load event rather than a fixed sleep, so all resources settle.
    got_load = any(e.get("method") == "Page.loadEventFired" for e in events)
    load_deadline = time.time() + 30
    while not got_load and time.time() < load_deadline:
        try:
            evt = recv()
        except Exception:
            break
        if evt.get("method") == "Page.loadEventFired":
            got_load = True
    if not got_load:
        time.sleep(0.5)  # fallback: give layout a moment

    # Await any async client rendering (e.g. Mermaid sets window.__carveReady).
    # Resolves immediately when the promise is absent.
    cmd("Runtime.enable")
    try:
        cmd("Runtime.evaluate", {
            "expression": "Promise.resolve(window.__carveReady).then(()=>true).catch(()=>true)",
            "awaitPromise": True,
            "returnByValue": True,
            "timeout": 20000,
        })
    except Exception:
        pass  # never let diagram rendering block the PDF

    result = cmd("Page.printToPDF", {
        "printBackground": True,
        "preferCSSPageSize": True,
        "displayHeaderFooter": DISPLAY_FOOTER,
        "headerTemplate": HEADER,
        "footerTemplate": FOOTER if DISPLAY_FOOTER else "<span></span>",
    })

    # Atomic write: temp then replace, so a failure never leaves a partial PDF.
    tmp = PDF.with_suffix(PDF.suffix + ".tmp")
    tmp.write_bytes(base64.b64decode(result["data"]))
    os.replace(tmp, PDF)
    print(f"wrote {PDF}")
finally:
    if ws is not None:
        try:
            ws.close()
        except Exception:
            pass
    chrome.terminate()
    try:
        chrome.wait(timeout=5)
    except Exception:
        chrome.kill()
    shutil.rmtree(profile, ignore_errors=True)
