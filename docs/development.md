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
