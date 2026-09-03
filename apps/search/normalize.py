"""Normalizarea textului pentru cautare.

Un singur mecanism, folosit identic la scriere (`match_text`) si la interogare, ca
sa se poata gasi „sedinta" cand s-a scris „ședință". Include si confuziile obisnuite
ale OCR-ului pe diacritice romanesti (ş cu sedila vs ș cu virgula).
"""

from __future__ import annotations

import re
import unicodedata

#: Diacriticele romanesti apar in doua variante Unicode. Le unificam inainte de NFD.
_EQUIVALENTS = {
    "ş": "ș",
    "Ş": "Ș",
    "ţ": "ț",
    "Ţ": "Ț",
    "ș": "ș",
    "ț": "ț",
}

_WHITESPACE = re.compile(r"\s+")
_TOKEN = re.compile(r"[0-9a-z]+")
_ORPHAN_PREPOSITION = re.compile(
    r"\b(?:la|[iî]n|pe|de|cu|pentru|[sș]i|ora|din)\s+(?=[,:;.]|$)", re.IGNORECASE
)
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,:;.])")


def strip_diacritics(text: str) -> str:
    for source, target in _EQUIVALENTS.items():
        text = text.replace(source, target)
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def normalize(text: str | None) -> str:
    """Litere mici, fara diacritice, spatii colapsate."""
    if not text:
        return ""
    return _WHITESPACE.sub(" ", strip_diacritics(text).lower()).strip()


def fold(text: str | None) -> str:
    """Ca `normalize`, dar pastreaza pozitiile caracterelor.

    Tiparele din parser sunt scrise fara diacritice, dar trebuie aplicate pe text
    cu diacritice. Cautam in versiunea „impaturita" si taiem din originalul
    aliniat pe aceleasi indici. Daca alinierea nu se poate pastra (caractere care
    se descompun in mai multe litere), returnam originalul in litere mici, ca sa
    nu producem taieturi gresite.
    """
    if not text:
        return ""
    folded = strip_diacritics(text).lower()
    return folded if len(folded) == len(text) else text.lower()


def cut_spans(text: str, spans: list[tuple[int, int]]) -> str:
    """Elimina intervalele date din text si normalizeaza spatiile ramase."""
    if not spans:
        return text
    keep: list[str] = []
    last = 0
    for start, end in sorted(spans):
        if start < last:
            start = last
        if end <= start:
            continue
        keep.append(text[last:start])
        last = end
    keep.append(text[last:])
    result = _WHITESPACE.sub(" ", "".join(keep))
    # Prepozitiile ramase orfane dupa taietura („pentru :") nu au ce cauta in titlu.
    result = _ORPHAN_PREPOSITION.sub("", result)
    result = _SPACE_BEFORE_PUNCT.sub(r"\1", result)
    return result.strip(" ,.;:-")


def tokens(text: str | None) -> list[str]:
    return _TOKEN.findall(normalize(text))
