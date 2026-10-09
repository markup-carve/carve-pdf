# What renders

carve-pdf renders the Carve core syntax plus the extension set of the
shopware-carve plugin, in static mode with raw HTML off. Code blocks have their own
page: [code-blocks.md](code-blocks.md).

## Extensions

Both backends enable these:

| Extension | What it adds |
|---|---|
| Admonitions | note, tip, warning and similar callout containers |
| Details | collapsible blocks, printed open |
| Spoiler | spoiler text; a block prints open with a dashed border, inline text prints shaded |
| Tabs | tabbed panels, printed one after another and labeled `Tab N` |
| Code group | tabbed code blocks with their own labels |
| List table | a table written as nested lists |
| Autolink | bare URLs become links |
| External links | off-site links get `rel="nofollow noopener"` and `target="_blank"` |
| Smart quotes | typographic quotes; `CARVE_SMART_LOCALE` picks the locale (PHP backend) |
| Math | `$`...`$` inline and `$$`...`$$` block math |
| Mermaid | ` ```mermaid ` diagrams |
| Chart | ` ```chart ` blocks |

Only the PHP backend also enables inline footnotes and the table of contents. Under
the JS backend, inline `[...]{.fn}` footnotes stay inline instead of becoming
numbered endnotes. Regular `[^1]` footnotes work the same in both.

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
