"""Publish a verified PDF without exposing a partial replacement."""

import os
from pathlib import Path
import shutil
import sys
import tempfile


source = Path(sys.argv[1])
destination = Path(sys.argv[2]).resolve()
staged = None
try:
    fd, staged = tempfile.mkstemp(prefix=".crv2pdf-", dir=destination.parent)
    with source.open("rb") as original, os.fdopen(fd, "wb") as copy:
        shutil.copyfileobj(original, copy)
    shutil.copymode(source, staged)
    os.replace(staged, destination)
except OSError as exc:
    sys.exit(f"publish_pdf.py: cannot write {destination}: {exc}")
finally:
    if staged is not None and os.path.exists(staged):
        os.unlink(staged)
