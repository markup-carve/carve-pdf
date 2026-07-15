# carve-pdf

Render [Carve](https://github.com/markup-carve) (`.crv`) documents to clean, paginated
PDFs. Faithful to the `shopware-carve` plugin's rendering (same extension set), with
section page-breaks and page numbers.

```bash
crv2pdf examples/demo.crv            # -> examples/demo.pdf
crv2pdf post.crv out.pdf             # explicit output
```

## Pipeline

```
render.php   Carve -> faithful HTML fragment (static + safe mode)
   |
wrap.py      + frontmatter (title/author/date/kicker) + <base href> + base.css + print.css
   |
print_cdp.py HTML -> PDF via Chrome DevTools (page-number footer, printBackground)
```

Why Chrome DevTools and not `chrome --print-to-pdf`: the CLI flag can't set a custom
footer (page numbers) and Blink ignores CSS `@bottom-center` counters. CDP gives both.

## Dependencies

| Need | For |
|------|-----|
| PHP 8.2+ and a `MarkupCarve\Carve` autoloader | `render.php` |
| Python 3 + `websocket-client` | `wrap.py`, `print_cdp.py` |
| Google Chrome or Chromium | PDF printing |

Point `render.php` at a Carve install via `CARVE_PHP_AUTOLOAD` (a `vendor/autoload.php`
that provides `MarkupCarve\Carve`). It also probes a few common locations.

## Frontmatter

The `.crv` frontmatter drives the document chrome:

```yaml
---yaml
title: "My Document"
description: "..."
author: Mark Scherer
date: 2026-07-15
kicker: "section · label"     # small caps header line (falls back to tags)
tags: [a, b, c]
lang: en
---
```

## Environment

| Var | Default | Meaning |
|-----|---------|---------|
| `CARVE_PHP_AUTOLOAD` | autodetect | Composer autoloader providing `MarkupCarve\Carve` |
| `CARVE_SMART_LOCALE` | `en` | Smart-quotes locale |
| `CHROME_BIN` | autodetect | Chrome/Chromium binary |

## Themes

Styling is two CSS files in `themes/`:

- `base.css` - the Carve construct vocabulary (admonitions, tables, tabs, code-group,
  footnotes, definition lists, math, ...). Target-agnostic; reusable for screen/email.
- `print.css` - paged-media layer: `@page`, section page-breaks, header/byline.

## Install (symlink onto PATH)

```bash
ln -s "$PWD/crv2pdf.sh" ~/.local/bin/crv2pdf
```

## Known limitations

- **Math** renders as raw TeX in `\(..\)` / `\[..\]` (static mode ships no KaTeX/MathJax).
- **Tabs** are auto-labeled `Tab N` in static output; use `code-group` for labeled tabs.
- **Images** must use relative or `https:` URLs - `data:` and `file:` URIs are neutralized
  by safe mode (an XSS defense inherited from carve-php). Relative paths resolve against
  the `.crv`'s directory via an injected `<base href>`.

See `examples/demo.crv` for a document exercising the full markup spectrum.
