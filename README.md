# carve-pdf

[![CI](https://github.com/markup-carve/carve-pdf/actions/workflows/ci.yml/badge.svg)](https://github.com/markup-carve/carve-pdf/actions/workflows/ci.yml)

Render Carve documents to paginated PDF through HTML and Chromium. On this `next2` branch the renderer uses the Carve 0.2 engines (carve-js and carve-php `next2`, pinned in `engine-pins.json`). See the [Carve documentation](https://markup-carve.github.io/carve/).

Use `--css FILE` for a stylesheet, `carve-pdf.css` beside an input for project
defaults, or `--theme NAME|DIR` for a named visual theme. The
[styling guide](docs/guide.md#custom-styling) covers order, safe frontmatter
tokens, print classes, and page headers and footers.

## Install

```sh
make install
```

## Usage

```sh
crv2pdf examples/demo.crv
```

In a container where Chromium cannot use its sandbox, run as a non-root user
with `CARVE_CHROME_NO_SANDBOX=1`. For example:

```sh
CARVE_CHROME_NO_SANDBOX=1 crv2pdf examples/demo.crv
```

## Language and print layout

Set frontmatter `lang` to `de`, `fr`, `es`, `nl`, or `it` to localize the byline and default page footer. English and unknown languages use "By" and "Page {page} of {pages}". Plain ISO dates in the byline use the document language's date format; other dates stay as written. `CARVE_PDF_FOOTER` overrides the selected theme and frontmatter `footer:`; an empty value disables the footer.

Code listings longer than 15 lines may split across pages. Short listings stay together.

## Documentation

- [Carve documentation](https://markup-carve.github.io/carve/)
- [Guide](docs/guide.md)
- [Documentation index](docs/README.md)
- [Contributing and development](docs/development.md)

## License

[MIT](LICENSE).
