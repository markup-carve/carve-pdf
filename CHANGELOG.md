# Changelog

All notable changes to carve-pdf are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

Nothing released yet. The initial capability set:

### Added

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
