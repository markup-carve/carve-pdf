# carve-pdf

[![CI](https://github.com/markup-carve/carve-pdf/actions/workflows/ci.yml/badge.svg)](https://github.com/markup-carve/carve-pdf/actions/workflows/ci.yml)

Render [Carve](https://github.com/markup-carve) (`.crv`) documents to clean, paginated
PDFs. Faithful to the `shopware-carve` plugin's rendering (same extension set), with
section page-breaks and page numbers.

```bash
crv2pdf examples/demo.crv            # -> examples/demo.pdf
crv2pdf post.crv out.pdf             # explicit output
crv2pdf post.crv --html              # standalone styled HTML  -> post.html
crv2pdf post.crv --md                # Markdown                -> post.md
crv2pdf post.crv --txt               # plain text              -> post.txt

crv2pdf a.crv b.crv c.crv --out-dir out/    # batch -> out/*.pdf
crv2pdf --watch post.crv                    # rebuild on every save
```

Output format defaults to `--pdf`. `--html` emits a self-contained styled document
(CSS inlined); `--md` / `--txt` use the renderer's native flattening converters.

**Batch.** Pass several `.crv` files (or set `--out-dir DIR`) to render each; outputs
are named `<basename>.<fmt>` beside the input or in `--out-dir`.

**Watch.** `--watch <input>` builds once, then rebuilds on every change. Uses
`inotifywait` when available (event-driven), else a 1s mtime poll - no extra deps.

## Pipeline

```
render.php / render.mjs   Carve -> faithful HTML fragment (static, raw HTML off)
   |
meta.py                   frontmatter -> JSON (renderer-independent)
   |
wrap.py                   + frontmatter (title/author/date/kicker) + <base href> + base.css + print.css
   |
print_cdp.py              HTML -> PDF via Chrome DevTools (page-number footer, printBackground)
```

Why Chrome DevTools and not `chrome --print-to-pdf`: the CLI flag can't set a custom
footer (page numbers) and Blink ignores CSS `@bottom-center` counters. CDP gives both.

## Backends

The Carve -> HTML step is pluggable. `CARVE_RENDERER` selects it (default `auto`):

| Backend | Script | Needs | Notes |
|---------|--------|-------|-------|
| `php` | `render.php` | PHP 8.2+ and a `MarkupCarve\Carve` autoloader | default when PHP is present |
| `js`  | `render.mjs` | Node 18+ and a carve-js checkout | runs PHP-free |

`auto` uses PHP if available, else Node. Both register the same extension set (the
shopware-carve plugin's) in static mode. Output is **equivalent, not byte-identical**:

- carve-js emits `<aside>` / `<h3>` where carve-php emits `<div role=...>` / `<p>` -
  `base.css` styles by class, so the rendered PDF looks the same either way.
- Inline `[...]{.fn}` footnotes are **numbered endnotes** under PHP (via its
  `InlineFootnotesExtension`) but plain inline `<span class="fn">` under JS (carve-js
  has no such extension). Regular `[^1]` footnotes work identically in both.

Point the backend at its library:
- `CARVE_PHP_AUTOLOAD` - a `vendor/autoload.php` providing `MarkupCarve\Carve`.
- `CARVE_JS` - a carve-js checkout dir or its `dist/index.js`.

Both probe a few common locations if unset.

## Dependencies

| Need | For |
|------|-----|
| A renderer backend (PHP **or** Node, see above) | `render.php` / `render.mjs` |
| Python 3 + `websocket-client` | `meta.py`, `wrap.py`, `print_cdp.py` |
| Google Chrome or Chromium | PDF printing |

## Frontmatter

The `.crv` frontmatter drives the document chrome:

```yaml
---yaml
title: "My Document"
description: "..."
author: Mark Scherer
date: 2026-07-15
kicker: "section · label"     # small caps header line (falls back to tags)
tags: [a, b, c]
lang: en
footer: "Page {page} of {pages}"   # optional; overrides $CARVE_PDF_FOOTER ("" disables)
paper: A4                           # A4 | Letter | "210mm 297mm" (PDF/HTML)
margin: "20mm 18mm"                 # any CSS @page margin
pageBreaks: h2                      # h2 (each ## a new page) | none | manual
---
```

**Page breaks.** `h2` (default) starts each top-level section on a fresh page; `none`
lets content flow; `manual` breaks only at an explicit `::: pagebreak` block in the
source. The `::: pagebreak` marker works in every mode.

**Math.** `$`...`$` inline and `$$`...`$$` block math are typeset with KaTeX (bundled,
offline) when a KaTeX install is found; point `CARVE_KATEX` at its `dist/` dir, or it
probes common locations. Without KaTeX, math degrades to readable raw TeX.

**Diagrams.** ` ```mermaid ` blocks are rendered to SVG at print time with Mermaid when
a `mermaid.min.js` is found; point `CARVE_MERMAID` at it, or it probes common locations.
Without Mermaid, the diagram source stays visible in a code block.

**Charts.** ` ```chart ` blocks (a Chart.js config as JSON) are drawn to a `<canvas>`
with Chart.js when `chart.umd.js` is found (`CARVE_CHART` or autodetect). Without it,
the JSON stays visible.

KaTeX, Mermaid, and Chart.js all render in Chrome under one `window.__carveReady`
promise that print_cdp awaits, so every renderer finishes before the PDF is captured.

## Environment

| Var | Default | Meaning |
|-----|---------|---------|
| `CARVE_RENDERER` | `auto` | Backend: `php`, `js`, or `auto` |
| `CARVE_PHP_AUTOLOAD` | autodetect | Composer autoloader providing `MarkupCarve\Carve` (php) |
| `CARVE_JS` | autodetect | carve-js checkout or `dist/index.js` (js) |
| `CARVE_SMART_LOCALE` | `en` | Smart-quotes locale (php backend) |
| `CARVE_PDF_FOOTER` | `Page {page} of {pages}` | Footer template; `{page}`/`{pages}` placeholders. Frontmatter `footer:` overrides it; empty string disables the footer |
| `CARVE_KATEX` | autodetect | KaTeX `dist/` dir for math typesetting |
| `CARVE_MERMAID` | autodetect | `mermaid.min.js` for diagram rendering |
| `CARVE_CHART` | autodetect | `chart.umd.js` for chart rendering |
| `CHROME_BIN` | autodetect | Chrome/Chromium binary |

The footer template accepts `{page}` and `{pages}`. Precedence: frontmatter `footer:`
> `CARVE_PDF_FOOTER` > the English default. Set it to an empty string to drop the
footer (and page numbers) entirely.

## Themes

Styling is two CSS files in `themes/`:

- `base.css` - the Carve construct vocabulary (admonitions, tables, tabs, code-group,
  footnotes, definition lists, math, ...). Target-agnostic; reusable for screen/email.
- `print.css` - paged-media layer: `@page`, section page-breaks, header/byline.

## Tests

`tests/test.sh` renders the fixtures under `tests/fixtures/` with every available
backend and asserts structural invariants (bold -> `<strong>`, `list-table` -> real
`<table>`, `mermaid`/`chart` blocks, page-geometry validation, ...). It runs whichever
of php/js is present and fails if neither is. CI (`.github/workflows/ci.yml`) builds
both carve-php and carve-js from their repos and runs it on every push.

```bash
./tests/test.sh
```

## Install (symlink onto PATH)

```bash
make install            # preflight deps, symlink -> ~/.local/bin/crv2pdf
make install PREFIX=/usr/local   # system-wide
make check              # dependency preflight only
make uninstall          # remove the symlink
```

Or symlink by hand: `ln -s "$PWD/crv2pdf.sh" ~/.local/bin/crv2pdf`.

## Known limitations

- **Math** is typeset with KaTeX when available (see above); otherwise it degrades to
  raw TeX in `\(..\)` / `\[..\]`.
- **Tabs** are auto-labeled `Tab N` in static output; use `code-group` for labeled tabs.
- **Images** must use relative or `https:` URLs - `data:` and `file:` URIs are neutralized
  by safe mode (an XSS defense inherited from carve-php). Relative paths resolve against
  the `.crv`'s directory via an injected `<base href>`.

See `examples/demo.crv` for a document exercising the full markup spectrum.
