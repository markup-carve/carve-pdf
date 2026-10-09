#!/usr/bin/env python3
"""Render an HTML file to PDF via Chrome DevTools Page.printToPDF.

Why CDP instead of `chrome --print-to-pdf`: the CLI flag can't set a custom
footer (page numbers), and Blink ignores CSS `@bottom-center` counters. CDP
gives footerTemplate + printBackground (keeps admonition colors).

Usage: print_cdp.py <input.html> <output.pdf> [footer-template]

The footer template is plain text with two placeholders, {page} and {pages}
(e.g. "Page {page} of {pages}" or "Seite {page} von {pages}"). Precedence:
argv[3], then $CARVE_PDF_FOOTER, then the English default. An empty template
disables the footer entirely.
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
import urllib.request
from pathlib import Path

try:
    import websocket  # websocket-client (synchronous)
except ImportError:
    sys.exit("print_cdp.py: needs the websocket-client package: pip install websocket-client")

if len(sys.argv) < 3:
    sys.exit("usage: print_cdp.py <input.html> <output.pdf> [footer-template]")

HTML = Path(sys.argv[1]).resolve()
PDF = Path(sys.argv[2]).resolve()
if not HTML.is_file():
    sys.exit(f"print_cdp.py: input not found: {HTML}")

# Footer template: argv[3] > $CARVE_PDF_FOOTER > English default. Empty -> no footer.
_default_footer = "Page {page} of {pages}"
if len(sys.argv) >= 4:
    footer_tpl = sys.argv[3]
else:
    footer_tpl = os.environ.get("CARVE_PDF_FOOTER", _default_footer)


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
                if t.get("type") == "page" and t.get("url", "").startswith("file:"):
                    _trace(
                        f"page target listed after {time.time() - started:.2f}s "
                        f"({attempts} attempt(s))"
                    )
                    return t["webSocketDebuggerUrl"]
            _trace(
                f"attempt {attempts} at {time.time() - started:.2f}s: "
                f"Chrome is up, no file: page target yet (types: "
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
        f"Chrome is running (pid {proc.pid}) but listed no file: page target "
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


port = free_port()
profile = tempfile.mkdtemp(prefix="carve-pdf-cdp-")
chrome = subprocess.Popen(
    [
        find_chrome(), "--headless=new", "--disable-gpu", "--no-sandbox",
        f"--remote-debugging-port={port}", "--remote-allow-origins=*",
        f"--user-data-dir={profile}", HTML.as_uri(),
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

    def cmd(method, params=None):
        global mid
        mid += 1
        ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") != mid:
                continue  # skip unrelated CDP events
            if "error" in msg:
                raise RuntimeError(f"CDP {method} failed: {msg['error']}")
            return msg.get("result", {})

    # Wait for the load event rather than a fixed sleep, so all resources settle.
    cmd("Page.enable")
    got_load = False
    for _ in range(200):  # ~10s cap
        try:
            evt = json.loads(ws.recv())
        except Exception:
            break
        if evt.get("method") == "Page.loadEventFired":
            got_load = True
            break
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
