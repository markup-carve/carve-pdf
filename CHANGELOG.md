# Changelog

All notable changes to carve-pdf are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Code callouts: `<1>` markers in a fence print as numbered badges that match
  the explanation list below the fence.
- A `::: toc` marker prints a table of contents at that spot.

### Fixed

- A `::: toc` marker no longer prints as an empty box.
- A ` ```math ` fence is typeset with KaTeX under the PHP backend instead of
  printing its TeX source.
- Skipped, deferred and question tasks (`[_]`, `[>]`, `[?]`) each print their
  own marker instead of the open-task circle.
- `tsx`, `json5`, `jsonl` and `vb` fences are highlighted.
- A PHP fence without a `<?php` opening tag is highlighted as PHP instead of
  printing as plain text.
- Mermaid diagrams use the body text size and font instead of Mermaid's 16px
  default, and sequence diagrams scale their boxes and gaps to match.
- Thematic breaks inside a section and the rule above the footnotes print
  again; only a break directly before a section that starts a new page is
  dropped.
- Inserted text is underlined without the edge slivers an inset shadow left in
  print, plain strikethrough keeps the body color, and an abbreviation's
  printed expansion is no longer underlined with it.
- Math typeset by KaTeX drops the code-style chip and box meant for raw TeX.
- Tables close their last row, nested lists add no gap inside their item, a
  figure's image is centered over its caption, and a figure group's caption
  spans the group.
- Code inside a quote is not italic, and a fence's `"Header"` prints in the top
  left corner of the listing.
- Tab and code-group panels print with even spacing and full-width labels, the
  byline stays with the content above it, and a chart keeps its margin.

## [0.1.2] - 2026-10-09

### Fixed

- A quote renders at document text contrast with a visible border, keeps the
  gap between its paragraphs and aligns its attribution with the quote body.
  The vendored carve-css layers move from a loose commit between 0.1.1 and
  0.1.2 to the published 0.1.4 (#22, markup-carve/carve-css#32).
- A captioned code listing is left-aligned instead of centered, long code
  lines wrap instead of being cut off at the page margin, and a paragraph
  introducing a listing stays on the same page as it (#23).
- A `{.diff}` fence is highlighted per line with its marker stripped, instead
  of as plain code reading `-` and `+` as operators, and its added and removed
  rows print tinted across the full block (#26).

### Added

- Every named code fence prints its language as a label in the top-right
  corner; `text`, `plain` and `none` fences and drawn mermaid and chart blocks
  stay unlabeled. Blade templates are highlighted, and fence names such as
  `yml`, `tsx`, `vue` and `patch` fall back to the nearest available lexer
  (#26).

## [0.1.1] - 2026-10-02

### Fixed

- `--pdf` without `websocket-client`, and `--html`/`--pdf` without `python3`,
  exit before rendering with the missing piece named instead of a Python
  traceback or `command not found` (#19).
- `--html` and `--pdf` no longer print a path inside the temporary work
  directory, and `--pdf` reports its output once (#19).

## [0.1.0] - 2026-10-02

First release. Everything below is new, so the list describes the capability
set rather than a delta.

### Added

- `crv2pdf` renders a `.crv` document to a paginated PDF through Chrome
  DevTools, with a page-number footer and `printBackground` enabled.
- Alternate output formats: `--html` (self-contained, CSS inlined), `--md` and
  `--txt` via the renderer's native flattening converters.
- `--version` prints the version the installed script was cut from.
- Batch rendering (several inputs, or `--out-dir DIR`) and `--watch`, which
  rebuilds on every save using `inotifywait` when present and a 1s mtime poll
  otherwise.
- Pluggable Carve to HTML backend selected by `CARVE_RENDERER`: `php`
  (`render.php`), `js` (`render.mjs`), or `auto`. Both register the extension
  set in static render mode.
- Themes under `themes/` and frontmatter support: title, author, date, kicker,
  page geometry (`paper`, `margin`) and a per-document `footer` template.
- `{{ path }}` include directives expand against the input's directory, with
  `--include-root DIR` to widen containment and `--no-includes` to leave them
  literal. A directive that escapes the root, names a missing file or forms a
  cycle reports itself and stays literal rather than failing the render.
- KaTeX math typesetting, Mermaid diagrams and Chart.js charts, each rendered
  to static output so the printed page carries them.
- Abbreviation expansions print inline, since a PDF has no hover.
- Static, print-safe syntax highlighting for named code fences, including a
  bundled first-party Carve lexer for `carve` and `crv` fences.
- The vendored `@markup-carve/carve-css` token, core, extension and recipe
  layers are inlined ahead of the PDF theme, so standalone output covers the
  current rendered vocabulary without needing npm at runtime. The vendored
  copy sits between carve-css 0.1.1 and 0.1.2; `themes/carve-css/UPSTREAM.md`
  names the exact commit.
- Both current engine spellings of keyboard input are styled (`<kbd>` and the
  compatibility `<span kbd>` form), so PHP- and JavaScript-backed PDFs agree.
- `make check` is a dependency preflight, `make install` symlinks `crv2pdf`
  onto PATH under an overridable `PREFIX`, and `make uninstall` removes it.
- An example set under `examples/`, covering structure, inline decorations,
  math and charts.
