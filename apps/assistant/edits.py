"""Ce anume cere o comandă de modificare să se schimbe.

Pana acum, orice `title` sau `description` nenul produs de interpretare se aplica
peste obiect. Cu parserul local scapa — pentru „Schimbă ora la 16" titlul iese gol —
dar modelul returneaza mereu un titlu, deci mutarea unei ore rescria si titlul, si
descrierea programarii. Utilizatorul pierdea text pe care nu il pusese nimeni in
discutie.

Aici se citeste determinist ce operatie a fost ceruta. Fara o formula explicita,
titlul si descrierea **raman neatinse**. Adaugarea la descriere nu inlocuieste nimic:
scrie la final, sub un separator, cu momentul modificarii in fusul utilizatorului.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from apps.core import dates_ro
from apps.search.normalize import fold

#: Linia care desparte o completare de textul dinaintea ei. Text simplu: continutul
#: ajunge intr-un camp de baza de date, nu intr-o pagina.
SEPARATOR = "────────────"

#: „Schimbă titlul în X", „Redenumește în X". Fara „în X" nu este o cerere completa.
_SET_TITLE = re.compile(
    r"\b(?:schimba|modifica|pune|seteaza)\s+(?:titlul|numele|denumirea)\s+(?:in|la|cu)\s+(.+)"
    r"|\bredenumeste(?:\s+in|\s+la)?\s+(.+)"
)

#: Aceleasi verbe, dar fara obiectul schimbarii: stim ce vrea, nu si in ce.
_TITLE_WITHOUT_VALUE = re.compile(
    r"\b(?:schimba|modifica|pune|seteaza)\s+(?:titlul|numele|denumirea)\s*$|\bredenumeste\s*$"
)

#: „Înlocuiește descrierea cu X", „Schimbă descrierea în X".
_REPLACE_DESCRIPTION = re.compile(
    r"\b(?:inlocuieste|schimba|modifica|rescrie)\s+(?:descrierea|detaliile|continutul)"
    r"\s+(?:cu|in|la)\s+(.+)"
)

_DESCRIPTION_WITHOUT_VALUE = re.compile(
    r"\b(?:inlocuieste|schimba|modifica|rescrie)\s+(?:descrierea|detaliile|continutul)\s*$"
)

#: „Adaugă că X", „Adaugă o notiță că X", „Completează cu X".
_APPEND_DESCRIPTION = re.compile(
    r"\badauga\s+(?:o\s+)?(?:notita|nota|mentiune|observatie)?\s*(?:ca|că|cu|:)\s+(.+)"
    r"|\bcompleteaza\s+(?:cu|ca)\s+(.+)"
    r"|\bnoteaza\s+(?:ca|cu)\s+(.+)"
)

_APPEND_WITHOUT_VALUE = re.compile(r"\badauga\s*$|\bcompleteaza\s*$")


@dataclass(frozen=True)
class EditRequest:
    """Ce a cerut utilizatorul explicit. `None` inseamna „nu schimba"."""

    title: str | None = None
    append: str | None = None
    replace_description: str | None = None
    #: Formula numeste campul, dar nu si valoarea noua. Nu ghicim: intrebam.
    ambiguous: bool = False

    @property
    def touches_text(self) -> bool:
        return bool(self.title or self.append or self.replace_description)


def detect(text: str) -> EditRequest:
    """Citeste din text ce s-a cerut pentru titlu si descriere.

    Pozitiile din textul „impaturit" corespund celui original, deci valoarea se taie
    din original si isi pastreaza diacriticele.
    """
    raw = (text or "").strip()
    folded = fold(raw)

    match = _SET_TITLE.search(folded)
    if match:
        return EditRequest(title=_value_from_raw(raw, match) or None)

    match = _REPLACE_DESCRIPTION.search(folded)
    if match:
        return EditRequest(replace_description=_value_from_raw(raw, match) or None)

    match = _APPEND_DESCRIPTION.search(folded)
    if match:
        return EditRequest(append=_value_from_raw(raw, match) or None)

    for pattern in (_TITLE_WITHOUT_VALUE, _DESCRIPTION_WITHOUT_VALUE, _APPEND_WITHOUT_VALUE):
        if pattern.search(folded):
            return EditRequest(ambiguous=True)

    return EditRequest()


def _value_from_raw(raw: str, match: re.Match) -> str:
    """Valoarea, taiata din textul original ca sa isi pastreze diacriticele."""
    for index, group in enumerate(match.groups(), start=1):
        if group:
            return raw[match.start(index) : match.end(index)].strip(" .,;:!?\"'")
    return ""


def append_to_description(existing: str, addition: str, moment: datetime) -> str:
    """Adauga la finalul descrierii, fara sa atinga ce era acolo.

    Fara separator cand nu exista text dinainte: o descriere goala nu are de ce sa
    inceapa cu o linie de despartire.
    """
    addition = addition.strip()
    if not addition:
        return existing
    if not existing.strip():
        return addition
    # `moment` vine deja in fusul utilizatorului. Filtrele din `dates_ro` reconvertesc
    # orice valoare „aware" in fusul activ al serverului, asa ca il predam fara fus:
    # altfel o modificare facuta la 09:30 la Londra ar fi scrisa ca 11:30.
    local = moment.replace(tzinfo=None)
    stamp = f"{dates_ro.format_date(local, with_year=True)}, {dates_ro.format_time(local)}"
    return f"{existing.rstrip()}\n\n{SEPARATOR}\nModificare · {stamp}\n{addition}"
