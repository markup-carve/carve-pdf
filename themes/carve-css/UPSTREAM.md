# Vendored carve-css

`tokens.css`, `core.css`, `extensions.css` and `recipes.css` are copied
byte-for-byte from `@markup-carve/carve-css`.

Pinned at commit `4a5d692` on `markup-carve/carve-css` main, synced 2026-10-01.
That is version 0.1.1 plus four stylesheet fixes - a block image rendering as a
block, a caption sitting against its image, a gallery tile spaced by the grid,
and a tab set and code group showing a panel in every render mode. The pin is a
commit rather than a tag because no release carried it when the sync happened.

Version 0.1.2 has since shipped and it does contain `4a5d692`, plus two further
stylesheet fixes the vendored copy does not have: a tab set pairing its radio
and panel without `:has()`, and an inline inside a highlight drawing on the
highlight's wash. So the vendored layers sit between 0.1.1 and 0.1.2, and the
next refresh should move to the 0.1.2 tag.

There is no local delta. All four files are byte-identical to the pin; verify it
against a carve-css checkout with
`git show 4a5d692:src/<file>.css | cmp - themes/carve-css/<file>.css`.

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
  reconciled rather than stacked.

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
