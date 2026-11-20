# What renders

carve-pdf renders Carve 0.2 core syntax and the provisional 0.2 standard extensions,
in static mode, with raw HTML off and the default URL policy. Code blocks are covered on
their own page: [code-blocks.md](code-blocks.md).

## Extensions

| Extension | What it adds | JS | PHP |
|---|---|---|---|
| Admonitions | note, tip, warning and similar callout containers (core) | yes | yes |
| Tabs | tabbed panels, printed one after another | yes | yes |
| Details | collapsible blocks, printed open | yes | yes |
| Spoiler | spoiler text; a block prints open, inline text prints revealed | yes | yes |
| Code group | tabbed code blocks with their own labels | yes | yes |
| List table | a table written as nested lists | yes | yes |
| External links | off-site links get `rel="nofollow noopener"` and `target="_blank"` | yes, as a document transform | yes |
| Math | `$`...`$` inline (core), `$$`...`$$` block math and ` ```math ` fences | yes | yes |
| Code callouts | `<1>` markers in a fence become numbered badges, bound to a `<1> text` list below it | yes | yes |
| Mermaid | ` ```mermaid ` diagrams | yes | yes |
| Chart | ` ```chart ` blocks | yes | yes |
| Smart quotes | typographic quotes; `CARVE_SMART_LOCALE` picks the locale | yes | yes |
| Table of contents | a `::: toc` marker prints the document's headings as links | yes, filled by carve-pdf | yes |

Without its extension a construct renders as the core node it parses as: a
` ```mermaid ` fence is a code block and `::: details` a `div`.

0.1 extensions that have no 0.2 counterpart are not rendered: autolink (a bare URL
stays text) and inline `[...]{.fn}` footnotes as endnotes.

## Math, diagrams and charts

These three need a client library at render time. None of them ships with
carve-pdf, neither in the repository nor in the Homebrew formula; install them
beside `crv2pdf.sh`:

```bash
npm install katex mermaid chart.js
```

| Feature | Library | Variable | Without it |
|---|---|---|---|
| Math | KaTeX | `CARVE_KATEX` (its `dist/` dir) | raw TeX in `\(..\)` / `\[..\]` |
| Diagrams | Mermaid | `CARVE_MERMAID` (`mermaid.min.js`) | the diagram source in a code block |
| Charts | Chart.js | `CARVE_CHART` (`chart.umd.js`) | the JSON config in a code block |

Each library resolves from its variable first, then `node_modules` beside
`crv2pdf.sh`, then `_deps/js`, then a sibling checkout. A found library is inlined
into the output, so the HTML and PDF need no network. When a document uses a feature
and its library is missing, the renderer says so on stderr and names the variable.
`make check` lists which libraries are present.

A ` ```chart ` block holds a Chart.js config as JSON. KaTeX, Mermaid and Chart.js
render in Chrome before the PDF is captured, and the capture waits for all three.
