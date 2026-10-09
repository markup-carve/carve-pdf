# Code blocks

Named fences such as ` ```php `, ` ```bash ` and ` ```carve ` are highlighted
statically with Pygments before HTML and PDF output. No browser script or network
request is involved. Without Pygments, fences stay readable but monochrome.

## Languages

Any fence name Pygments knows is highlighted. Its
[lexer list](https://pygments.org/docs/lexers/) is the full set of names and aliases.

carve-pdf bundles two lexers Pygments lacks:

| Fence | Lexer |
|---|---|
| `carve`, `crv` | Carve block and inline syntax |
| `blade` | Laravel Blade templates |

A few names Pygments lacks, at least in older releases, fall back to the closest
lexer:

| Fence | Highlighted as |
|---|---|
| `yml`, `neon` | YAML |
| `tsx` | JSX |
| `jsonc`, `jsonl` | JSON |
| `json5` | JavaScript |
| `vb` | VB.NET |
| `vue`, `svelte`, `astro`, `latte` | HTML |
| `env`, `dotenv` | Bash |
| `svg` | XML |
| `patch` | diff |
| `hbs`, `mustache` | Handlebars |
| `gql` | GraphQL |

The fallbacks live in `LEXER_FALLBACKS` in `lib/wrap.py`.

A PHP fence without `<?php` is highlighted as PHP code, not as HTML around it.

A language Pygments does not know at all (`csv`, `typst`) prints unhighlighted but
keeps its label.

Some lexers do not cover every construct of their language. Pygments' SCSS lexer
marks a top-level `$variable:` as an error, and the HTML fallback for Svelte marks
the `=` in `on:click={...}`. Error tokens print in red.

## Labels and headers

Every named fence shows its language as a small label in the top-right corner, in
HTML and PDF alike. `text`, `txt`, `plain`, `plaintext` and `none` fences, and the
drawn `mermaid` and `chart` blocks, get no label.

A fence's `"Header"` (` ```php "src/App.php" `) prints in the top-left corner.

## Diffs

`{.diff}` above a language fence marks it as a diff: each line's leading `+`, `-` or
space is the marker, added and removed lines print on green and red rows, and the
rest of the line is highlighted in the fence's language. The markup matches the
`diff/carve-diff.css` contract in carve-grammars.
