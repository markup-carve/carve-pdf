#!/usr/bin/env python3
"""Evaluate a JS expression against an HTML file in headless Chrome, print JSON.

Why this exists: a grep over the stylesheets cannot see a panel that renders at
`display: none`, is occluded, or collapses to zero height. Those are resolved
values, so only a browser can report them. Same CDP plumbing as print_cdp.py.

Usage: probe_cdp.py <input.html> <expression.js>

The expression is read from a file and evaluated with `awaitPromise`, so it may
be a promise. Its value is printed as JSON on stdout. A thrown expression exits
non-zero with the message on stderr.
"""
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

if len(sys.argv) != 3:
    sys.exit("usage: probe_cdp.py <input.html> <expression.js>")

HTML = Path(sys.argv[1]).resolve()
EXPR_FILE = Path(sys.argv[2]).resolve()
if not HTML.is_file():
    sys.exit(f"probe_cdp.py: input not found: {HTML}")
if not EXPR_FILE.is_file():
    sys.exit(f"probe_cdp.py: expression not found: {EXPR_FILE}")
EXPR = EXPR_FILE.read_text(encoding="utf-8")


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
    sys.exit("probe_cdp.py: no Chrome/Chromium binary found (set $CHROME_BIN)")


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
profile = tempfile.mkdtemp(prefix="carve-pdf-probe-")
chrome = subprocess.Popen(
    [
        find_chrome(), "--headless=new", "--disable-gpu", "--no-sandbox",
        f"--remote-debugging-port={port}", "--remote-allow-origins=*",
        "--window-size=1200,2400",
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

    cmd("Runtime.enable")
    try:
        cmd("Runtime.evaluate", {
            "expression": "Promise.resolve(window.__carveReady).then(()=>true).catch(()=>true)",
            "awaitPromise": True,
            "returnByValue": True,
            "timeout": 20000,
        })
    except Exception:
        pass  # never let diagram rendering block the probe

    res = cmd("Runtime.evaluate", {
        "expression": EXPR,
        "awaitPromise": True,
        "returnByValue": True,
        "timeout": 20000,
    })
    if "exceptionDetails" in res:
        detail = res["exceptionDetails"]
        text = (detail.get("exception") or {}).get("description") or detail.get("text")
        print(f"probe_cdp.py: expression threw: {text}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(res["result"].get("value")))
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
