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
crv2pdf post.crv --css brand.css --css print-tweaks.css
crv2pdf post.crv --theme classic
crv2pdf post.crv --theme ./my-theme
```

Output format defaults to `--pdf`. `--html` emits a self-contained styled document
(CSS inlined); `--md` / `--txt` use the engine's Markdown and plain-text exports (JS backend).

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

**Images and links.** When printing a PDF, an image loads only from the input's
directory (or the `--include-root` directory). A path that leads elsewhere, through
`../`, an absolute path or a symlink, is blocked, and so is any `http(s)` image; each
block is reported on stderr and the document prints without that image.

- `--allow-remote` fetches `http(s)` images. Each one is bounded to 10 seconds and
  10 MB (`CARVE_PDF_REMOTE_TIMEOUT`, `CARVE_PDF_REMOTE_MAX_BYTES`).
- `--link-base URL` resolves relative links such as `[next](chapter2.crv)` against a
  URL. Without it a relative link stays relative in `--html` output and prints as
  plain text in a PDF, where it could only point into the build machine's filesystem.

In `--html` output, image paths stay relative to the HTML file, so write it next to
the source (the default) or copy the images along. CSS asset and import paths are
resolved relative to the final HTML output location.

## Custom styling

`--css FILE` adds a trusted stylesheet. Repeat it to apply files in command line
order. `carve-pdf.css` beside the input is loaded automatically before these
files. With `--include-root DIR`, the project file is sought in that directory
instead. PDF and `--html` use the same styles. Local `url()` assets resolve from
each stylesheet's directory; those directories join the PDF printer's local
resource allowlist. Local CSS imports keep their cascade position, and their
directories are allowed for assets too. Remote URLs and imports still require
`--allow-remote` for PDF printing.

Styles apply in this order: vendored `carve-css`, the selected theme, print
rules, checked document tokens and page settings, the project stylesheet, then
each `--css` file. The last trusted stylesheet may override earlier rules, but
normal CSS specificity still applies. For example, `.carve h1` overrides the
built-in `.carve h1` when declared later, while bare `h1` may not.

`--theme NAME|DIR` uses `themes/NAME` or a directory you provide. A theme has
`theme.css` in place of `base.css`, optional local fonts or images, and a
`theme.json` object. Its supported defaults are `paper`, `margin`, `header`,
and `footer`. `classic` is bundled and matches the original visual theme. The
CSS contract is the `carve-css` class vocabulary. The project's CSS and CLI
styles override theme CSS. For footer text, the order is
`CARVE_PDF_FOOTER` > theme default > document `footer` > language default.
An empty footer disables page numbers. For geometry, checked document values
override theme defaults, while project or CLI CSS has the last word.

Chrome 131 or newer prints the footer in the CSS `@page` bottom margin box.
Custom CSS can replace it with another margin box, style page numbers, add a
fixed header, or use `@page :first`, `:left`, and `:right`. Older Chrome uses
the DevTools footer template. `{page}` and `{pages}` remain available in a
footer value. A theme `header` is fixed text; running chapter headers are not
supported by Chrome.

Authors can add `.page-break`, `.keep-together`, `.landscape`, `.no-print`, or
`.columns-2` to blocks with Carve attributes. They respectively start a page,
keep a block on one page, use a named landscape page, omit a block from print,
or set it in two columns. `.no-print` remains visible in the screen HTML.

Document frontmatter cannot select a CSS file. The supported `pdf` keys are:

| Key | CSS property | Accepted value |
|-----|--------------|----------------|
| `accent` | `--carve-accent` | 3 or 6 digit hex color |
| `font` | `--carve-font-body` | One font family name, letters, digits, spaces, hyphens, up to 80 characters |
| `font-size` | `--pdf-font-size` | 6 to 30 pt or px, at most two decimal places |
| `line-height` | `--carve-line-height` | Number from 1 to 2.99, at most two decimal places |

For example:

```yaml
---yaml
pdf:
  accent: "#0a5"
  font: "Source Serif 4"
  font-size: 10.5pt
  line-height: 1.5
---
```

Invalid values are ignored with a warning. The document's validated `paper`,
`margin`, and `pageBreaks` keys remain available. There is no document CSS path
or trust toggle.

## Pipeline

```
render.php / render.mjs   Carve -> faithful HTML fragment (static, raw HTML off)
   |
meta.py                   frontmatter block (as the engine parsed it) -> JSON keys
   |
wrap.py                   + frontmatter + selected theme + print.css + trusted CSS
   |
print_cdp.py              HTML -> PDF via Chrome DevTools (printBackground, local resource guard)
```

Chrome DevTools also supplies PDF bookmarks, author metadata, and a fallback
footer template for Chrome before 131.

## Backends

The Carve -> HTML step is pluggable. `CARVE_RENDERER` selects it (default `auto`):

| Backend | Script | Needs | Notes |
|---------|--------|-------|-------|
| `js`  | `render.mjs` | Node 20+ and the Carve 0.2 `@markup-carve/carve` package | default; the complete backend |
| `php` | `render.php` | PHP 8.2+ and a Carve 0.2 `MarkupCarve\Carve` autoloader | fewer extensions; no `--md` / `--txt` yet |

`auto` picks Node when it can actually load the Carve 0.2 package, else PHP, else it
reports what to install. An interpreter on PATH is not enough, and a Carve 0.1 engine
does not count. Setting `CARVE_RENDERER` explicitly skips the probe, so asking for a
backend reports that backend's own error.

Output is **equivalent, not byte-identical**. carve-php 0.2 does not have all the
standard extensions yet; [rendering.md](rendering.md#extensions) lists what each
backend renders. `--md` and `--txt` use the 0.2 Markdown and plain-text exports of
the engine the backend runs.

Carve 0.2 is not released yet. On the `next2` branch, CI builds both engines from the
commits that `engine-pins.json` names. Locally, point the backends at a checkout of
each engine's `next2`.

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
footer: "Page {page} of {pages}"   # optional; host footer and theme take precedence
pdf:
  accent: "#0a5"
  font: "Source Serif 4"
  font-size: 10.5pt
  line-height: 1.5
paper: A4                           # A4 | Letter | "210mm 297mm" (PDF/HTML)
margin: "20mm 18mm"                 # any CSS @page margin
pageBreaks: h2                      # h2 (each ## a new page) | none | manual
---
```

The block is read as the engine parses it, so `---`, `--- yaml` and `---json` all
work; `json` content is parsed as JSON, anything else as `key: value` lines with
`# comments` dropped. `author` also becomes the PDF's Author, and every PDF carries a
heading outline (bookmarks).

**Page breaks.** `h2` (default) starts each top-level section on a fresh page; `none`
lets content flow; `manual` breaks only at an explicit `::: pagebreak` block in the
source. The `::: pagebreak` marker works in every mode.

**Code.** Named fences such as ` ```php ` and ` ```carve ` are highlighted with
Pygments, labeled with their language, and can be marked as diffs. Supported
languages, fallbacks and the diff markup are in [docs/code-blocks.md](../docs/code-blocks.md).

**Math, diagrams and charts.** KaTeX math, ` ```mermaid ` diagrams and ` ```chart `
blocks render when their library is installed (`npm install katex mermaid chart.js`);
without it the source stays visible. The full extension set and how each library is
found are in [docs/rendering.md](../docs/rendering.md).

## Environment

| Var | Default | Meaning |
|-----|---------|---------|
| `CARVE_RENDERER` | `auto` | Backend: `js`, `php`, or `auto` |
| `CARVE_PHP_AUTOLOAD` | autodetect | Composer autoloader providing `MarkupCarve\Carve` (php) |
| `CARVE_JS` | autodetect | carve-js dist dir or `dist/index.js`, e.g. under `node_modules` (js) |
| `CARVE_SMART_LOCALE` | `en` | Smart-quotes locale (js backend) |
| `CARVE_PDF_FOOTER` | Theme, document, or language default | Host footer template with `{page}`/`{pages}` placeholders; empty string disables it |
| `CARVE_KATEX` | autodetect | KaTeX `dist/` dir for math typesetting |
| `CARVE_MERMAID` | autodetect | `mermaid.min.js` for diagram rendering |
| `CARVE_CHART` | autodetect | `chart.umd.js` for chart rendering |
| `CHROME_BIN` | autodetect | Chrome/Chromium binary |
| `CARVE_CHROME_NO_SANDBOX` | unset | `1` starts Chrome without its sandbox. Only for a host that cannot provide one; running as root does this automatically |
| `CARVE_PDF_REMOTE_TIMEOUT` | `10` | Seconds per remote image with `--allow-remote` |
| `CARVE_PDF_REMOTE_MAX_BYTES` | `10485760` | Size limit per remote image with `--allow-remote` |

The byline uses the primary subtag of `lang` for its author label and plain ISO date format. Supported languages are English, German, French, Spanish, Dutch, and Italian. Other languages use English labels. Dates in other formats stay as written.

The footer template accepts `{page}` and `{pages}`. The host's
`CARVE_PDF_FOOTER` and selected theme default take precedence over document
`footer`; an empty value removes page numbers.

Code listings longer than 15 lines may split across pages. Shorter listings stay together.

## Themes

Styling is the released `carve-css` 0.1.7 construct vocabulary followed by two
PDF-specific layers in `themes/`:

- `carve-css/{tokens,core,extensions,recipes}.css` - byte-for-byte vendored from the
  stylesheet package so standalone installs cover the current rendered vocabulary.
- `base.css` - the existing carve-pdf visual theme and compatibility overrides.
- `print.css` - paged-media layer: `@page`, section page-breaks, header/byline.
- `classic/` - bundled named theme with the original visual styles.

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

- **Tabs** are auto-labeled `Tab N` in static output; use `code-group` for labeled tabs.
- **Images** must use relative paths inside the document's directory, or `http(s)`
  URLs together with `--allow-remote`. `data:` and `file:` URIs are neutralized by safe
  mode (an XSS defense inherited from carve-php).
- **Untrusted documents.** Headless Chrome runs with its sandbox on, unless carve-pdf
  runs as root or `CARVE_CHROME_NO_SANDBOX=1` is set; in a container, prefer a non-root
  user. Request interception covers the printed page and its same-process frames.

See `examples/demo.crv` for a document exercising the full markup spectrum, and
[`examples/README.md`](../examples/README.md) for the smaller focused examples
(structure, inline decorations, math / diagrams / charts).

## Development

Contributor setup, testing, and maintenance notes are in the [development guide](../docs/development.md).
