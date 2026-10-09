"""Pygments lexer for Laravel Blade templates.

Pygments ships none. Blade is HTML with three constructs on top: `{{-- --}}`
comments, `{{ }}` / `{!! !!}` echoes holding a PHP expression, and `@directive`
calls whose arguments are PHP. Everything else is handed to the HTML lexer, the
same split Pygments uses for Smarty and Jinja inside HTML.
"""
import re

from pygments.lexer import DelegatingLexer, RegexLexer, bygroups, using
from pygments.lexers.html import HtmlLexer
from pygments.lexers.php import PhpLexer
from pygments.token import Comment, Keyword, Other, Punctuation


class _BladeTagLexer(RegexLexer):
    flags = re.DOTALL

    tokens = {
        "root": [
            (r"\{\{--.*?--\}\}", Comment.Multiline),
            (r"(\{!!)(.*?)(!!\})",
             bygroups(Comment.Preproc, using(PhpLexer, startinline=True), Comment.Preproc)),
            (r"(\{\{)(.*?)(\}\})",
             bygroups(Comment.Preproc, using(PhpLexer, startinline=True), Comment.Preproc)),
            # `@@if` prints a literal `@if`; an `@` after a word character, as in
            # an e-mail address, is not a directive (Blade's own `\B@` rule).
            (r"@@\w+", Other),
            (r"(?<!\w)(@\w+)(\()", bygroups(Keyword, Punctuation), "args"),
            (r"(?<!\w)@\w+", Keyword),
            (r"[^{@]+", Other),
            (r"[{@]", Other),
        ],
        # Directive arguments are PHP; parentheses nest, as in `@if(count($a) > 1)`,
        # and a quoted one does not count: `@if($x === "(")`.
        "args": [
            (r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', using(PhpLexer, startinline=True)),
            (r"\(", Punctuation, "#push"),
            (r"\)", Punctuation, "#pop"),
            (r"[^()\"']+", using(PhpLexer, startinline=True)),
            (r"[\"']", using(PhpLexer, startinline=True)),
        ],
    }


class BladeLexer(DelegatingLexer):
    name = "Blade"
    aliases = ["blade"]
    filenames = ["*.blade.php"]

    def __init__(self, **options):
        super().__init__(HtmlLexer, _BladeTagLexer, **options)
