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

import websocket  # websocket-client (synchronous)

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


def page_ws(port: int, deadline: float) -> str:
    """Bounded retry (not a background loop) to find the page target ws URL."""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/json", timeout=2
            ) as resp:
                for t in json.load(resp):
                    if t.get("type") == "page" and t.get("url", "").startswith("file:"):
                        return t["webSocketDebuggerUrl"]
        except Exception:
            pass
        time.sleep(0.15)
    raise RuntimeError("Chrome DevTools page target not found within timeout")


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
        page_ws(port, time.time() + 15), max_size=None, timeout=30
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
