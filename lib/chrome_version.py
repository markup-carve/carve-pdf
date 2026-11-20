"""Small Chrome version feature gate, isolated from the CDP print lifecycle."""
import re
import subprocess


def supports_margin_boxes(browser: str) -> bool:
    """Page margin boxes first shipped in Chrome 131."""
    try:
        version = subprocess.check_output([browser, "--version"], text=True, timeout=5)
        match = re.search(r"\b(?:Chrome(?: for Testing)?|Chromium|HeadlessChrome)[\s/]+(\d+)\b", version)
        return bool(match and int(match.group(1)) >= 131)
    except (OSError, subprocess.SubprocessError):
        return False
