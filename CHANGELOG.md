# Changelog

All notable changes to carve-pdf are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

Nothing released yet. The initial capability set:

### Added

- Vendor the released `@markup-carve/carve-css` 0.1.0 token, core and extension
  layers and inline them before the existing PDF theme, keeping standalone
  output current without requiring npm at runtime.
- Style both current engine spellings of keyboard input (`<kbd>` and the
  compatibility `<span kbd>` form) so PHP- and JavaScript-backed PDFs agree.

- `crv2pdf` renders a `.crv` document to a paginated PDF through Chrome
  DevTools, with a page-number footer and `printBackground` enabled.
- Alternate output formats: `--html` (self-contained, CSS inlined), `--md` and
  `--txt` via the renderer's native flattening converters.
- Batch rendering (several inputs, or `--out-dir DIR`) and `--watch`, which
  rebuilds on every save using `inotifywait` when present and a 1s mtime poll
  otherwise.
- Pluggable Carve -> HTML backend selected by `CARVE_RENDERER`: `php`
  (`render.php`), `js` (`render.mjs`), or `auto`. Both register the
  shopware-carve extension set in static mode.
- Themes under `themes/` and frontmatter support (title, author, date, kicker).
