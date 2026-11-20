#!/usr/bin/env python3
"""Corpus content-loss gate.

Renders a sample of the Carve corpus through carve-pdf's own renderer setup and
reports every case whose output drops words the corpus HTML carries. Markup is
free to differ (static mode, safe mode, extensions); text going missing is not.
That is how a legacy extension registered over the engine core went unnoticed
while it dropped container labels in seven corpus cases.

Usage: corpus-content.py <corpus-dir|examples.json> [--backend php|js]... [--sample N]

The sample is deterministic: an even stride over the sorted cases plus every
case named in ALWAYS. Exit 1 on any unexplained loss.
"""
import argparse
import html
import json
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

LIB = Path(__file__).resolve().parent.parent / "lib"

# Cases that lost text once; they are checked on every run.
ALWAYS = (
    "42-admonitions-4",
    "255-colon-fence-metadata-slots-must-be-a-space-too-5",
    "496-a-title-or-label-fills-the-container-body-slot-2",
    "518-a-trailing-comment-takes-a-tab-a-run-start-and-its-whole-separator-9",
    "529-a-container-label-publishes-its-inline-run-5",
    "529-a-container-label-publishes-its-inline-run-6",
    "529-a-container-label-publishes-its-inline-run-7",
)

TAG = re.compile(r"<[^>]*>")
WORD = re.compile(r"\w+", re.UNICODE)
RAW_BLOCK = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)


def words(markup: str) -> Counter:
    text = html.unescape(TAG.sub(" ", RAW_BLOCK.sub(" ", markup)))
    return Counter(w.lower() for w in WORD.findall(text))


def render(backend: str, path: Path) -> str:
    cmd = ["php", str(LIB / "render.php")] if backend == "php" else ["node", str(LIB / "render.mjs")]
    proc = subprocess.run(cmd + ["--no-includes", str(path)], capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else f"exit {proc.returncode}")
    return proc.stdout


def example_cases(path: Path):
    """Use the default render cases whose expected HTML matches host defaults."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("kind") != "examples" or not isinstance(data.get("examples"), list):
        raise ValueError(f"not a conformance examples file: {path}")
    return sorted(
        (case for case in data["examples"]
         if case.get("kind") == "render" and case.get("options") == {}
         and isinstance(case.get("input"), str)
         and isinstance(case.get("expected", {}).get("html"), str)),
        key=lambda case: case["id"],
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus")
    ap.add_argument("--backend", action="append", choices=("php", "js"))
    ap.add_argument("--sample", type=int, default=300)
    args = ap.parse_args()

    corpus = Path(args.corpus)
    examples = corpus.is_file()
    cases = example_cases(corpus) if examples else sorted(
        p for p in corpus.glob("*.crv") if p.with_suffix(".html").is_file()
    )
    if not cases:
        print(f"corpus-content: no render cases with expected HTML in {corpus}", file=sys.stderr)
        return 1
    stride = max(1, len(cases) // max(1, args.sample))
    chosen = cases[::stride] if examples else sorted(
        set(cases[::stride]) | {corpus / f"{n}.crv" for n in ALWAYS if (corpus / f"{n}.crv").is_file()}
    )

    failed = 0
    for backend in args.backend or ["php", "js"]:
        losses, errors = [], []
        with tempfile.TemporaryDirectory(prefix="carve-corpus-") as tmp:
            for case in chosen:
                name = case["id"] if examples else case.stem
                if examples:
                    source = Path(tmp) / f"{name}.crv"
                    source.write_text(case["input"], encoding="utf-8")
                    expected = case["expected"]["html"]
                else:
                    source = case
                    expected = case.with_suffix(".html").read_text(encoding="utf-8")
                try:
                    ours = words(render(backend, source))
                except Exception as exc:  # a crash is a loss of everything
                    errors.append(f"{name}: render failed: {exc}")
                    continue
                missing = words(expected) - ours
                if not missing:
                    continue
                sample = ", ".join(f"{w}x{n}" if n > 1 else w for w, n in missing.most_common(8))
                losses.append(f"{name}: missing {sum(missing.values())} word(s): {sample}")
        print(f"== corpus content ({backend}): {len(chosen)} cases, "
              f"{len(losses)} lose text, {len(errors)} fail to render ==")
        for line in errors + losses:
            print(f"  FAIL - {line}")
        failed += len(losses) + len(errors)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
