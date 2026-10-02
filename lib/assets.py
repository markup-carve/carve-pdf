"""Where the optional client-side libraries live.

KaTeX, Mermaid, and Chart.js are resolved from an environment variable first and
otherwise from a node_modules relative to this file, never from an absolute path:
carve-pdf ships as a tarball, so a path that is right on one machine is a leak
on every other. `make check` and wrap.py share this module so the preflight
cannot drift from what the renderer actually looks at.

Run as a script to print one status line per library.
"""
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

# What `npm install` at the repo root lays down (also where the Homebrew formula
# puts the package, under libexec/), the repo's own _deps/js install that CI
# builds, and a sibling carve-js checkout for engine work.
NODE_ROOTS = (
    _ROOT / "node_modules",
    _ROOT / "_deps" / "js" / "node_modules",
    _ROOT.parent / "carve-js" / "node_modules",
)


def node_paths(*parts):
    """The given package-relative path under each node_modules root."""
    return [root.joinpath(*parts) for root in NODE_ROOTS]


# (env var, npm package, what the document loses without it, how to find it)
LIBRARIES = (
    ("CARVE_KATEX", "katex", "math renders as raw TeX", "dir"),
    ("CARVE_MERMAID", "mermaid", "diagrams stay source code", "file"),
    ("CARVE_CHART", "chart.js", "charts stay JSON", "file"),
)

_RELATIVE = {
    "katex": ("katex", "dist"),
    "mermaid": ("mermaid", "dist", "mermaid.min.js"),
    "chart.js": ("chart.js", "dist", "chart.umd.js"),
}


def _usable(path, kind):
    # KaTeX is a directory, and only one holding katex.min.css is any use.
    return Path(path, "katex.min.css").is_file() if kind == "dir" else Path(path).is_file()


def locate(package, kind):
    """The library's path, or None. Does not read the environment."""
    return next((p for p in node_paths(*_RELATIVE[package]) if _usable(p, kind)), None)


def resolve(env_name, package, kind):
    """(path, env_ignored): the library's path from $env_name or the defaults."""
    value = os.environ.get(env_name)
    if value:
        if _usable(value, kind):
            return Path(value), None
        return locate(package, kind), value
    return locate(package, kind), None


def main():
    for env_name, package, lost, kind in LIBRARIES:
        found, ignored = resolve(env_name, package, kind)
        if ignored is not None:
            print(f"  WARN {package + ':':17} ${env_name} is set but unusable ({ignored})")
        if found is None:
            print(f"  WARN {package + ':':17} missing - {lost} (npm install {package}, or ${env_name})")
        else:
            print(f"  {package + ':':22}yes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
