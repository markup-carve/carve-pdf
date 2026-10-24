"""Check delimited fences after the PDF wrapper's static highlighting step."""

from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as directory:
    source = Path(directory) / "delimited.crv"
    output = Path(directory) / "delimited.html"
    source.write_text(
        "# Delimited data\n\n```csv\nname,value\na,b\n```\n\n"
        "```tsv\nname\tvalue\na\tb\n```\n",
        encoding="utf-8",
    )
    subprocess.run([str(ROOT / "crv2pdf.sh"), str(source), str(output), "--html"], check=True)
    html = output.read_text(encoding="utf-8")
    for language, separator in (("csv", ","), ("tsv", "\t")):
        block = re.search(rf'<code class="language-{language} syntax-highlighted">(.*?)</code>', html, re.S)
        assert block, f"missing highlighted {language} fence"
        assert f'<span class="tok-ow">{separator}</span>' in block[1], language
        assert '<span class="tok-gs">name</span>' in block[1], language
    css = (ROOT / "themes/base.css").read_text(encoding="utf-8")
    assert ".tok-ow { color: #9f1239; }" in css
    assert ".tok-sx { color: #16794b; }" in css
    print("CSV and TSV separators have a distinct token and color")
