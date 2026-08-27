# Vendored carve-css

These files are copied byte-for-byte from `@markup-carve/carve-css` 0.1.0,
tagged at `3876baa`. They are vendored because `carve-pdf` is a standalone shell
CLI and its self-contained HTML/PDF output cannot depend on an npm installation.

Refresh `tokens.css`, `core.css`, `extensions.css`, and `recipes.css` together when carve-css is
released. `themes/base.css` remains the PDF theme's visual override layer and
`themes/print.css` remains its paged-media layer.
