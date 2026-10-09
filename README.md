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
crv2pdf book/main.crv --include-root .      # {{ path }} includes contained to the cwd
```

Output format defaults to `--pdf`. `--html` emits a self-contained styled document
(CSS inlined); `--md` / `--txt` use the renderer's native flattening converters.

**Batch.** Pass several `.crv` files (or set `--out-dir DIR`) to render each; outputs
are named `<basename>.<fmt>` beside the input or in `--out-dir`.

**Watch.** `--watch <input>` builds once, then rebuilds on every change. Uses
`inotifywait` when available (event-driven), else a 1s mtime poll - no extra deps.
It also rebuilds when a file the document includes changes. An include that did not
resolve is not watched, so creating the missing file needs a save of the input.

**Includes.** `{{ path }}` directives expand before rendering, in every output format.
Paths resolve against the file that writes them, and nothing outside the containment
root is read: by default that root is the input document's directory.

- `--include-root DIR` sets a different root. A relative path resolves against the
  directory you run the command from.
- `--no-includes` leaves directives literal.

A directive that cannot be resolved stays in the output as written, and a warning
naming it goes to stderr. Warnings name files relative to the root. Includes need a
carve-php or carve-js that ships the include pass; with an older engine the directives
stay literal and a warning says so.

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
| `js`  | `render.mjs` | Node 18+ and the `markup-carve/carve` npm package | runs PHP-free |

`auto` picks PHP when it can actually load a `MarkupCarve\Carve` autoloader, else
Node, else it reports what to install. An interpreter on PATH is not enough: a machine
with PHP but no carve-php would otherwise be sent to the PHP backend and fail there
while a working Node engine sat unused. Setting `CARVE_RENDERER` explicitly skips the
probe, so asking for a backend reports that backend's own error.

Both register the same extension set (the shopware-carve plugin's) in static mode.
Output is **equivalent, not byte-identical**:

- carve-js emits `<aside>` / `<h3>` where carve-php emits `<div role=...>` / `<p>` -
  `base.css` styles by class, so the rendered PDF looks the same either way.
- Inline `[...]{.fn}` footnotes are **numbered endnotes** under PHP (via its
  `InlineFootnotesExtension`) but plain inline `<span class="fn">` under JS (carve-js
  has no such extension). Regular `[^1]` footnotes work identically in both.

Both engines are published, so neither backend needs a checkout:

```bash
composer require markup-carve/carve-php
npm install "@markup-carve/carve"
```

Point the backend at its library:
- `CARVE_PHP_AUTOLOAD` - a `vendor/autoload.php` providing `MarkupCarve\Carve`,
  such as the `vendor/autoload.php` Composer writes.
- `CARVE_JS` - a carve-js dist dir or its `dist/index.js`, such as
  `node_modules/@markup-carve/carve/dist/index.js`. A checkout works too.

If unset, both look beside the `crv2pdf.sh` they were invoked through, in this order:
a `node_modules` / `vendor` directory next to it (what `npm install` or
`composer require` in this directory produces, and where a Homebrew install puts
them), this repo's own `_deps/js` and `_deps/php` install, then a sibling checkout.
No absolute path is ever consulted, so the same tarball resolves the same way on
every machine.

## Dependencies

Only one thing is required: a renderer backend that can load a Carve engine. Everything
else narrows what you can produce. `make check` reports each one and what its absence
costs, and fails only when no engine resolves.

| Need | Required for | Without it |
|------|--------------|------------|
| A renderer backend, PHP **or** Node, with its engine (see above) | everything | nothing renders |
| Python 3 | `--html`, `--pdf` | `--md` and `--txt` still work |
| `websocket-client` | `--pdf` | `--html`, `--md`, `--txt` still work |
| Google Chrome or Chromium | `--pdf` | `--html`, `--md`, `--txt` still work |
| Pygments | highlighted code fences | fences render readable but unhighlighted |
| KaTeX | math | math renders as raw TeX |
| Mermaid | ` ```mermaid ` blocks | the diagram source stays visible |
| Chart.js | ` ```chart ` blocks | the chart JSON stays visible |
| `inotifywait` | `--watch` responsiveness | `--watch` falls back to polling |

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

**Code.** Named fences such as ` ```php `, ` ```bash `, and ` ```carve ` are
highlighted statically with Pygments before HTML/PDF output. The bundled Carve lexer
understands Carve's own block and inline syntax; no browser script or network request
is needed. Without Pygments, fences remain readable but monochrome.

Blade (` ```blade `) uses a bundled lexer as well, since Pygments has none. A few
names that older Pygments releases lack fall back to the closest lexer: `yml` and
`neon` to YAML, `tsx` to TypeScript, `jsonc`/`json5` to JSON, `vue`, `svelte`, `astro`
and `latte` to HTML, `env` to Bash, `svg` to XML, `patch` to diff, `hbs`/`mustache` to
Handlebars, `gql` to GraphQL. A language Pygments does not know at all (`csv`, `typst`)
prints unhighlighted.

Every named fence shows its language as a small label in the top-right corner, in HTML
and PDF alike. `text`, `txt`, `plain` and `none` fences, and the drawn `mermaid` and
`chart` blocks, get no label.
A fence's `"Header"` (` ```php "src/App.php" `) prints in the top-left corner.

`{.diff}` above a language fence marks it as a diff: each line's leading `+`, `-` or
space is the marker, added and removed lines print on green and red rows, and the
rest of the line is highlighted in the fence's language. The markup matches the
`diff/carve-diff.css` contract in carve-grammars.

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

All three are optional and resolve like the engines: `CARVE_KATEX` / `CARVE_MERMAID` /
`CARVE_CHART` first, then `node_modules/katex`, `node_modules/mermaid` and
`node_modules/chart.js` beside `crv2pdf.sh`, then `_deps/js`, then a sibling checkout.
Install them with `npm install katex mermaid chart.js`. When a document uses one and
it cannot be found, the renderer says so on stderr and names the variable rather than
dropping the math, diagram or chart in silence. `make check` lists which are present.

## Environment

| Var | Default | Meaning |
|-----|---------|---------|
| `CARVE_RENDERER` | `auto` | Backend: `php`, `js`, or `auto` |
| `CARVE_PHP_AUTOLOAD` | autodetect | Composer autoloader providing `MarkupCarve\Carve` (php) |
| `CARVE_JS` | autodetect | carve-js dist dir or `dist/index.js`, e.g. under `node_modules` (js) |
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

Styling is the released `carve-css` 0.1.5 construct vocabulary followed by two
PDF-specific layers in `themes/`:

- `carve-css/{tokens,core,extensions,recipes}.css` - byte-for-byte vendored from the
  stylesheet package so standalone installs cover the current rendered vocabulary.
- `base.css` - the existing carve-pdf visual theme and compatibility overrides.
- `print.css` - paged-media layer: `@page`, section page-breaks, header/byline.

## Install (symlink onto PATH)

```bash
make install            # preflight deps, symlink -> ~/.local/bin/crv2pdf
make install PREFIX=/usr/local   # system-wide
make check              # dependency preflight only
make uninstall          # remove the symlink
```

Or symlink by hand: `ln -s "$PWD/crv2pdf.sh" ~/.local/bin/crv2pdf`.

Check which version is on PATH with `crv2pdf --version`.

## Known limitations

- **Math** is typeset with KaTeX when available (see above); otherwise it degrades to
  raw TeX in `\(..\)` / `\[..\]`.
- **Tabs** are auto-labeled `Tab N` in static output; use `code-group` for labeled tabs.
- **Images** must use relative or `https:` URLs - `data:` and `file:` URIs are neutralized
  by safe mode (an XSS defense inherited from carve-php). Relative paths resolve against
  the `.crv`'s directory via an injected `<base href>`.

See `examples/demo.crv` for a document exercising the full markup spectrum, and
[`examples/README.md`](examples/README.md) for the smaller focused examples
(structure, inline decorations, math / diagrams / charts).

## Development

Contributor setup, testing, and maintenance notes are in the [development guide](docs/development.md).
