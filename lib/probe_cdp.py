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
        wait_for_page_ws(port, chrome, "probe_cdp.py"), max_size=None, timeout=30
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
