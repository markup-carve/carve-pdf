"""Byline and footer labels for document languages."""
import re
import json
import sys


LABELS = {
    "en": ("By", "Page {page} of {pages}", None),
    "de": ("Von", "Seite {page} von {pages}", "."),
    "fr": ("Par", "Page {page} sur {pages}", "/"),
    "es": ("Por", "Página {page} de {pages}", "/"),
    "nl": ("Door", "Pagina {page} van {pages}", "-"),
    "it": ("Di", "Pagina {page} di {pages}", "/"),
}


def labels(lang):
    primary = str(lang or "en").split("-", 1)[0].split("_", 1)[0].lower()
    return LABELS.get(primary, LABELS["en"])


def local_date(value, lang):
    date = str(value)
    separator = labels(lang)[2]
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", date)
    if match and separator:
        year, month, day = match.groups()
        return separator.join((day, month, year))
    return date


if __name__ == "__main__":
    meta = json.loads(open(sys.argv[1], encoding="utf-8").read())
    print(labels(meta.get("lang"))[1], end="")
