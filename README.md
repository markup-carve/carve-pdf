# carve-pdf

[![CI](https://github.com/markup-carve/carve-pdf/actions/workflows/ci.yml/badge.svg)](https://github.com/markup-carve/carve-pdf/actions/workflows/ci.yml)

Render Carve documents to paginated PDF through HTML and Chromium. The renderer uses Carve engines and styles matching Carve 0.1 output. See the [Carve documentation](https://markup-carve.github.io/carve/).

## Install

```sh
make install
```

## Usage

```sh
crv2pdf examples/demo.crv
```

## Language and print layout

Set frontmatter `lang` to `de`, `fr`, `es`, `nl`, or `it` to localize the byline and default page footer. English and unknown languages use "By" and "Page {page} of {pages}". Plain ISO dates in the byline use the document language's date format; other dates stay as written. Frontmatter `footer:` overrides `CARVE_PDF_FOOTER`, which overrides the language default. An empty footer value disables the footer.

Code listings longer than 15 lines may split across pages. Short listings stay together.

## Documentation

- [Carve documentation](https://markup-carve.github.io/carve/)
- [Guide](docs/guide.md)
- [Documentation index](docs/README.md)
- [Contributing and development](docs/development.md)

## License

[MIT](LICENSE).
