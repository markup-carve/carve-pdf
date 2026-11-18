#!/usr/bin/env python3
"""Styling contract independent of an installed Carve engine."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "lib"))
from chrome_version import supports_margin_boxes

CSS = HERE / "themes"
BUILTINS = [CSS / "carve-css" / name for name in
            ("tokens.css", "core.css", "extensions.css", "recipes.css")]
BUILTINS += [CSS / "base.css", CSS / "print.css"]


class Styling(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="carve-pdf-styling-"))
        (self.root / "fragment.html").write_text("<h1>Test</h1>", encoding="utf-8")
        (self.root / "meta.json").write_text("{}", encoding="utf-8")

    def wrap(self, meta=None, options=(), print_mode=False, env=None):
        (self.root / "meta.json").write_text(json.dumps(meta or {}), encoding="utf-8")
        cmd = ["python3", str(HERE / "lib" / "wrap.py")]
        if print_mode:
            cmd.append("--print")
        cmd += list(options) + [str(self.root / "fragment.html"),
                str(self.root / "meta.json"), str(self.root),
                str(self.root / "out.html")] + [str(p) for p in BUILTINS]
        proc = subprocess.run(cmd, text=True, capture_output=True,
                              env={**os.environ, **(env or {})})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return (self.root / "out.html").read_text(encoding="utf-8"), proc.stderr

    def test_tokens_and_untrusted_values(self):
        html, stderr = self.wrap({"pdf": {"accent": "#0a5", "font": "Source Serif 4",
                                          "font-size": "10.5pt", "line-height": "1.5",
                                          "unknown": "red", "danger": "red; } body { color:red"}})
        self.assertIn("--carve-accent: #0a5;", html)
        self.assertIn('--carve-font-body: "Source Serif 4";', html)
        self.assertIn("--pdf-font-size: 10.5pt;", html)
        self.assertIn("--carve-line-height: 1.5;", html)
        self.assertNotIn("body { color:red", html)
        self.assertIn("ignoring invalid pdf token `unknown`", stderr)

    def test_host_css_order_and_local_urls(self):
        project = self.root / "carve-pdf.css"
        cli = self.root / "brand.css"
        project.write_text(".carve h1 { color: green; }\n", encoding="utf-8")
        cli.write_text(".carve h1 { color: blue; background: url('fonts/a.woff2'); }\n", encoding="utf-8")
        options = ("--custom-css", str(project), "--custom-css", str(cli))
        html, _ = self.wrap({"pdf": {"accent": "#0a5"}}, options)
        self.assertLess(html.index("--carve-accent: #0a5"), html.index("color: green"))
        self.assertLess(html.index("color: green"), html.index("color: blue"))
        self.assertIn("url('fonts/a.woff2')", html)
        printed, _ = self.wrap(options=options, print_mode=True)
        self.assertIn("url('file://" + str(self.root) + "/fonts/a.woff2')", printed)

    def test_css_import_keeps_its_cascade_position_and_dependency(self):
        imported = self.root / "imported.css"
        imported.write_text(".carve h1 { color: purple; }", encoding="utf-8")
        host = self.root / "host.css"
        host.write_text('@import "imported.css";\n.carve h1 { font-weight: bold; }', encoding="utf-8")
        deps = self.root / "css-deps"
        options = ("--css-deps-out", str(deps), "--custom-css", str(host))
        html, _ = self.wrap(options=options)
        self.assertIn('<style>\n@import "imported.css";', html)
        self.assertLess(html.index("--carve-accent"), html.index('@import "imported.css"'))
        self.assertIn(str(imported), deps.read_text())
        printed, _ = self.wrap(options=options, print_mode=True)
        self.assertIn('@import "file://' + str(imported) + '"', printed)

    def test_import_accepts_css_whitespace_and_comments(self):
        imported = self.root / "imported.css"
        imported.write_text('body { color: purple; }', encoding="utf-8")
        host = self.root / "host.css"
        host.write_text('@import\n/* note */ "imported.css";')
        deps = self.root / "css-deps"
        options = ("--css-deps-out", str(deps), "--custom-css", str(host))
        printed, _ = self.wrap(options=options, print_mode=True)
        self.assertIn('/* note */ "file://' + str(imported) + '"', printed)
        self.assertIn(str(imported), deps.read_text())
        host.write_text('@import\nurl("imported.css");')
        printed, _ = self.wrap(options=options, print_mode=True)
        self.assertIn('url("file://' + str(imported) + '")', printed)
        self.assertIn(str(imported), deps.read_text())

    def test_all_imports_on_one_line_are_discovered(self):
        styles = self.root / "styles"
        sibling = self.root / "sibling"
        styles.mkdir()
        sibling.mkdir()
        (styles / "one.css").write_text('body { color: blue; }')
        (sibling / "two.css").write_text('body { color: red; }')
        host = styles / "host.css"
        host.write_text('@import "one.css"; @import "../sibling/two.css";')
        deps = self.root / "css-deps"
        printed, _ = self.wrap(options=("--css-deps-out", str(deps), "--custom-css", str(host)), print_mode=True)
        self.assertIn(str(styles / "one.css"), deps.read_text())
        self.assertIn(str(sibling / "two.css"), deps.read_text())
        self.assertIn((sibling / "two.css").as_uri(), printed)

    def test_html_assets_use_final_output_directory(self):
        styles = self.root / "styles with spaces"
        styles.mkdir()
        host = styles / "host.css"
        host.write_text('@import "more.css";\nbody { background: url(icon.svg); }')
        exported = self.root / "export" / "report.html"
        html, _ = self.wrap(options=("--asset-base", str(exported), "--custom-css", str(host)))
        self.assertIn('@import "../styles%20with%20spaces/more.css"', html)
        self.assertIn('url(../styles%20with%20spaces/icon.svg)', html)
        self.assertNotIn("carve-pdf-styling-", html.split("@import", 1)[1])

    def test_literal_url_text_is_untouched(self):
        host = self.root / "host.css"
        host.write_text('/* url(comment.svg) */\nbody::before { content: "url(icon.svg)"; background: url(icon.svg); }')
        exported = self.root / "export" / "report.html"
        html, _ = self.wrap(options=("--asset-base", str(exported), "--custom-css", str(host)))
        self.assertIn('/* url(comment.svg) */', html)
        self.assertIn('content: "url(icon.svg)"', html)
        self.assertIn('background: url(../icon.svg)', html)

    def test_theme_defaults_and_host_footer(self):
        theme = self.root / "theme.json"
        theme.write_text(json.dumps({"paper": "Letter", "margin": "15mm",
                                     "footer": "Theme {page}", "header": "Fixed"}))
        footer = self.root / "footer"
        header = self.root / "header"
        args = ("--theme-config", str(theme), "--footer-out", str(footer),
                "--header-out", str(header))
        html, _ = self.wrap({"paper": "A5", "footer": "Document {page}"}, args)
        self.assertIn("size: A5;", html)
        self.assertIn("@page carve-landscape { size: A5 landscape; }", html)
        self.assertIn("margin: 15mm;", html)
        self.assertIn('content: "Theme " counter(page)', html)
        self.assertEqual(footer.read_text(), "Theme {page}")
        self.assertEqual(header.read_text(), "Fixed")
        html, _ = self.wrap({"footer": "Document {page}"}, args,
                            env={"CARVE_PDF_FOOTER": "Host {pages}"})
        self.assertIn('content: "Host " counter(pages)', html)

    def test_landscape_matches_custom_paper(self):
        html, _ = self.wrap({"paper": "210mm 297mm"})
        self.assertIn("@page carve-landscape { size: 297mm 210mm; }", html)

    def test_nested_pdf_frontmatter(self):
        doc = self.root / "doc.crv"
        doc.write_text('---yaml\ntitle: Test\npdf:\n  accent: "#0a5"\n  line-height: 1.5\n---\n',
                       encoding="utf-8")
        out = subprocess.check_output(["python3", str(HERE / "lib" / "meta.py"), str(doc)], text=True)
        self.assertEqual(json.loads(out)["pdf"], {"accent": "#0a5", "line-height": "1.5"})

    def test_footer_cannot_end_style_element(self):
        html, _ = self.wrap({"footer": '</style><script>alert(1)</script>'})
        self.assertNotIn('</style><script>alert(1)', html)
        self.assertIn('\\3c /style>', html)

    def test_chrome_for_testing_version_gate(self):
        browser = self.root / "fake-chrome"
        for label, expected in (("Google Chrome for Testing 156.0.0.0", True),
                                ("Google Chrome 130.0.0.0", False),
                                ("Chromium 131.0.0.0", True)):
            browser.write_text('#!/bin/sh\necho "' + label + '"\n', encoding="utf-8")
            browser.chmod(0o755)
            self.assertEqual(supports_margin_boxes(str(browser)), expected, label)


if __name__ == "__main__":
    unittest.main()
