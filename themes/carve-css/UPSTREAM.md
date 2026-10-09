# Vendored carve-css

`tokens.css`, `core.css`, `extensions.css` and `recipes.css` are copied
byte-for-byte from `@markup-carve/carve-css`.

Vendored from markup-carve/carve-css version 0.1.5, commit 818245f (the tag
commit), synced 2026-10-09. The pin is a released tag, not a loose commit. The
org dependency map reads this line, so keep its shape when re-syncing.

What this sync brings over 0.1.4 (`98209de`): static tab, code-group and
spoiler panels no longer take core's heading-section gap above them
(markup-carve/carve-css#37). `themes/base.css` carried a local `margin: 0` on
the panels for that until now; it is gone again.

There is no local delta. Only `extensions.css` changed; the other three were
already byte-identical. Verify against a carve-css checkout with
`git show 818245f:src/<file>.css | cmp - themes/carve-css/<file>.css`.

## Why this is vendored

`carve-pdf` is a standalone shell CLI. `wrap.py` inlines these four files into
the single self-contained HTML document it prints from, so it needs them as
paths on disk at build time and cannot resolve an npm package. That reason
still holds: nothing in the repo runs `npm`, and the CLI installs by symlinking
`crv2pdf.sh` onto PATH.

What vendoring is NOT doing here is carrying print-specific edits. There are
none. `themes/base.css` is the visual override layer and `themes/print.css` the
paged-media layer, and both sit on top rather than inside these files. Keeping
the vendored copies at zero delta is deliberate: a divergence here is drift, and
the next refresh should be a straight overwrite.

## Not vendored, on purpose

The pin also ships `carve.css`, `contrast.css` and `print.css`.

- `carve.css` is the aggregate that imports the others. `wrap.py` inlines the
  four parts itself, so the aggregate would be a second route to the same bytes.
- `contrast.css` carries the high-contrast palettes and the `forced-colors`
  remap. Both are reader preferences a browser applies; a printed PDF has one
  fixed palette, and `print_cdp.py` never emulates either.
- `print.css` upstream is a screen stylesheet's print adjustments.
  `themes/print.css` is this repo's own paged-media layer, with the page
  geometry that frontmatter drives. Adopting upstream's would need the two
  reconciled rather than stacked. 0.1.4 adds two quote tokens to it,
  `--carve-quote-ink` and `--carve-quote-border`, which only pin the defaults
  `core.css` already resolves on the quote: ink to `--carve-ink` either way, and
  the border to `--carve-border` instead of a 50 percent mix of ink and surface.
  So the quote fix reaches a printed PDF through `core.css` alone, and the one
  thing vendoring `print.css` would change is a slightly firmer quote border -
  a visual choice for `themes/base.css` or `themes/print.css` to make here, not
  a reason to adopt a whole upstream layer.

Revisit any of the three if `crv2pdf` grows a themed-HTML output that a reader
views on screen, where contrast preferences start to mean something.

## Refreshing

Overwrite all four together from one carve-css commit, then update the pin,
version and date above. Run `./tests/panels.sh`, which renders a tab set and a
code group and asks a browser and the printed PDF whether the panels are on the
page. That gate exists because the previous pin hid every panel in every render
mode and no assertion over the CSS text could see it.

`themes/base.css` deliberately no longer overrides panel visibility. If a
refresh makes it necessary again, the fix belongs upstream: an override here
masks the gate.
