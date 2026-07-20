# Examples

Carve source (`.crv`) with the rendered PDF next to each one. Regenerate one, or all:

```sh
./crv2pdf.sh examples/01-spec.crv          # -> examples/01-spec.pdf
./crv2pdf.sh examples/*.crv                # batch -> examples/*.pdf
```

| Source | PDF | Shows |
| ------ | --- | ----- |
| [`demo.crv`](demo.crv) | `demo.pdf` | The full markup spectrum in one document: every admonition, tabs, `code-group`, `list-table`, line block, definition list, footnotes, spoilers, abbreviations, smart typography. Uses the default `pageBreaks: h2`, so each `##` starts a fresh page. |
| [`01-spec.crv`](01-spec.crv) | `01-spec.pdf` | Structural constructs: headings, nested / ordered / task lists, a table with a header row, definition list, block quote with attribution, fenced code, thematic break. |
| [`02-showcase.crv`](02-showcase.crv) | `02-showcase.pdf` | Every inline decoration (bold, italic, underline, strikethrough, highlight, super/subscript), a captioned image, critic markup, an admonition, and a table with **row and column spans**. |
| [`03-math-diagrams.crv`](03-math-diagrams.crv) | `03-math-diagrams.pdf` | **Math, diagrams and charts**: inline and display math via KaTeX, two Mermaid flowcharts, and a Chart.js chart. |

The three numbered examples set `pageBreaks: none` in their frontmatter so short
documents flow instead of spending a page per section; `demo.crv` keeps the default.

## Math, diagrams and charts

Unlike a server-side PDF engine, `crv2pdf` renders these *in the browser* at print
time - KaTeX for math, Mermaid for ` ```mermaid ` fences, Chart.js for ` ```chart `
fences. All three resolve under one `window.__carveReady` promise that `print_cdp.py`
awaits, so nothing is captured half-drawn.

Each library is autodetected, or point at it explicitly:

```sh
CARVE_KATEX=/path/to/katex/dist \
CARVE_MERMAID=/path/to/mermaid.min.js \
CARVE_CHART=/path/to/chart.umd.js \
  ./crv2pdf.sh examples/03-math-diagrams.crv
```

Without a given library the construct degrades to its readable source (raw TeX, or
the fence's code block) rather than failing the render.
