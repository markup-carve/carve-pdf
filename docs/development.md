# Development

## Tests

`tests/test.sh` renders the fixtures under `tests/fixtures/` with every available
backend and asserts structural invariants (bold -> `<strong>`, `list-table` -> real
`<table>`, `mermaid`/`chart` blocks, page-geometry validation, ...). It runs whichever
of php/js is present and fails if neither is. CI (`.github/workflows/ci.yml`) builds
both carve-php and carve-js from their repos and runs it on every push.

```bash
./tests/test.sh
```

## Cutting a release

The version lives in two places: `CRV2PDF_VERSION` in `crv2pdf.sh`, which is what
`crv2pdf --version` prints, and the newest `## [x.y.z]` heading in `CHANGELOG.md`.
Move both, then tag the commit that carries them.

`.github/workflows/tag.yml` runs on every tag push. It refuses the tag unless its
name agrees with both of those, and then runs the whole suite against the released
engines, so the leak guard sits between a tag and a release rather than after it.

Rehearse before tagging. The same workflow takes a tag name as a dispatch input and
checks the branch you point it at:

```bash
gh workflow run tag.yml --ref main -f tag=0.1.0
```

`tests/version-gate.sh <tag>` is the check on its own, and `tests/test.sh` runs it
both ways so a pull request shows it going red as well as green.
