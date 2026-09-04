"""Interpretarea expresiilor temporale in limba romana.

`dateparser` acopera bine formele scrise („6 septembrie 2026", „06.09.2026"), dar
vorbirea curenta foloseste expresii pe care le rezolvam explicit inainte:
„mâine dimineața", „marți viitoare", „peste două săptămâni", „la trei și jumătate".

Toate tiparele sunt scrise fara diacritice si se aplica pe versiunea „impaturita"
a textului (`normalize.fold`), aliniata caracter cu caracter cu originalul. Asa
putem taia exact fragmentele consumate, pastrand diacriticele in restul textului.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

import dateparser

from apps.search.normalize import cut_spans, fold

WEEKDAYS = {
    "luni": 0,
    "marti": 1,
    "miercuri": 2,
    "joi": 3,
    "vineri": 4,
    "sambata": 5,
    "simbata": 5,
    "duminica": 6,
}

MONTHS = {
    "ianuarie": 1,
    "februarie": 2,
    "martie": 3,
    "aprilie": 4,
    "mai": 5,
    "iunie": 6,
    "iulie": 7,
    "august": 8,
    "septembrie": 9,
    "octombrie": 10,
    "noiembrie": 11,
    "decembrie": 12,
}

NUMBER_WORDS = {
    "o": 1,
    "un": 1,
    "una": 1,
    "doua": 2,
    "doi": 2,
    "trei": 3,
    "patru": 4,
    "cinci": 5,
    "sase": 6,
    "sapte": 7,
    "opt": 8,
    "noua": 9,
    "zece": 10,
    "unsprezece": 11,
    "doisprezece": 12,
    "douasprezece": 12,
}

#: Numeralele acceptate ca ora rostita: „la trei", „la două".
#:
#: `o`, `un`, `una` si `doi` sunt excluse intentionat. „La o întâlnire" si „la un
#: control" sunt cele mai obisnuite continuari ale prepozitiei; citite ca ora, ar
#: inventa 01:00 dintr-o fraza care nu contine nicio ora.
HOUR_WORDS = {
    word: value for word, value in NUMBER_WORDS.items() if word not in {"o", "un", "una", "doi"}
}

#: Parti de zi -> ora implicita.
DAY_PARTS = {
    "dimineata": time(9, 0),
    "dimineaza": time(9, 0),
    "la pranz": time(12, 0),
    "amiaza": time(12, 0),
    "dupa-amiaza": time(15, 0),
    "dupa amiaza": time(15, 0),
    "seara": time(19, 0),
    "noaptea": time(22, 0),
}

RELATIVE_DAYS = {
    "raspoimaine": 3,
    "poimaine": 2,
    "astazi": 0,
    "maine": 1,
    "azi": 0,
    "ieri": -1,
}

_HOUR_WORDS_ALT = "|".join(sorted(HOUR_WORDS, key=len, reverse=True))

#: Dupa un numeral rostit ca ora trebuie sa urmeze sfarsitul frazei, un semn de
#: punctuatie sau un cuvant care nu poate fi substantivul pe care il determina.
#: Fara aceasta conditie, „la noua adresă" ar deveni ora 09:00.
_HOUR_WORD_TAIL = (
    r"(?=\s*$|[,.;!?]|\s+(?:cu|si|fix|la|in|pe|dupa|dimineata|dimineaza|"
    r"amiaza|seara|noaptea|pm|am)\b)"
)

_TIME_HHMM = re.compile(r"\b(?:la\s+|ora\s+)?([01]?\d|2[0-3])[:.,]([0-5]\d)\b")
_TIME_HOUR = re.compile(
    r"\b(?:la|ora|orele)\s+(?:"
    r"(" + _HOUR_WORDS_ALT + r")\b" + _HOUR_WORD_TAIL + r"|"
    r"([01]?\d|2[0-3])\b(?![:.,]?\d)"
    r")"
)
_TIME_HALF = re.compile(r"\b(?:la|ora)\s+([a-z]+|\d{1,2})\s+si\s+jumatate\b")
_TIME_QUARTER = re.compile(r"\b(?:la|ora)\s+([a-z]+|\d{1,2})\s+si\s+un\s+sfert\b")
_DATE_NUMERIC = re.compile(r"\b(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?\b")
_DATE_MONTH = re.compile(r"\b(?:pe\s+)?(\d{1,2})\s+(" + "|".join(MONTHS) + r")\b(?:\s+(\d{4}))?")
_IN_N_UNITS = re.compile(r"\bpeste\s+([a-z]+|\d+)\s+(minute?|ore?|zile?|saptamani?|luni)\b")
_WEEKDAY = re.compile(
    r"\b(?:in\s+|pe\s+)?(" + "|".join(WEEKDAYS) + r")\b(\s+viitoare|\s+viitor)?"
)


@dataclass(frozen=True)
class TemporalMatch:
    day: date | None = None
    at_time: time | None = None
    end_time: time | None = None
    #: Intervalele consumate din text, ca sa nu ramana in titlu.
    spans: tuple[tuple[int, int], ...] = ()
    ambiguous: bool = False
    reason: str = ""

    @property
    def has_value(self) -> bool:
        return self.day is not None or self.at_time is not None


def word_to_number(word: str) -> int | None:
    word = word.strip()
    if word.isdigit():
        return int(word)
    return NUMBER_WORDS.get(word)


def _next_weekday(reference: date, weekday: int, *, force_next_week: bool) -> date:
    delta = (weekday - reference.weekday()) % 7
    if delta == 0:
        delta = 7
    if force_next_week:
        delta += 7
    return reference + timedelta(days=delta)


def _find_day_part(folded: str) -> tuple[time, tuple[int, int]] | None:
    """Cauta partile de zi, cele mai lungi intai.

    Ordinea conteaza: „amiaza" este continut in „dupa-amiaza". Cautat primul, ar
    da 12:00 acolo unde s-a spus 15:00, si ar taia din text doar jumatatea a doua.
    """
    for word in sorted(DAY_PARTS, key=len, reverse=True):
        index = folded.find(word)
        if index != -1:
            return DAY_PARTS[word], (index, index + len(word))
    return None


def extract(text: str, *, now: datetime) -> TemporalMatch:
    """Extrage data si ora dintr-o comanda. Ce nu e clar ramane None."""
    folded = fold(text)
    today = now.date()
    spans: list[tuple[int, int]] = []
    day: date | None = None
    at_time: time | None = None
    ambiguous = False
    reason = ""

    # 1. Zile relative: azi / mâine / poimâine (cele mai lungi intai).
    for word, offset in RELATIVE_DAYS.items():
        match = re.search(rf"\b{word}\b", folded)
        if match:
            day = today + timedelta(days=offset)
            spans.append(match.span())
            break

    # 2. „peste N zile / ore / săptămâni".
    match = _IN_N_UNITS.search(folded)
    if match and day is None:
        count = word_to_number(match.group(1))
        unit = match.group(2)
        if count:
            if unit.startswith("minut"):
                moment = now + timedelta(minutes=count)
                day, at_time = moment.date(), moment.time().replace(second=0, microsecond=0)
            elif unit.startswith("or"):
                moment = now + timedelta(hours=count)
                day, at_time = moment.date(), moment.time().replace(second=0, microsecond=0)
            elif unit.startswith("zi"):
                day = today + timedelta(days=count)
            elif unit.startswith("saptaman"):
                day = today + timedelta(weeks=count)
            elif unit.startswith("lun"):
                day = today + timedelta(days=30 * count)
            spans.append(match.span())

    # 3. Data numerica: 06.09.2026.
    match = _DATE_NUMERIC.search(folded)
    if match and day is None:
        d, m, y = match.groups()
        year = today.year if y is None else (2000 + int(y) if len(y) == 2 else int(y))
        try:
            day = date(year, int(m), int(d))
            spans.append(match.span())
        except ValueError:
            ambiguous, reason = True, "data_invalida"

    # 4. „6 septembrie" / „6 septembrie 2026".
    match = _DATE_MONTH.search(folded)
    if match and day is None:
        d, month_name, y = match.groups()
        year = int(y) if y else today.year
        try:
            candidate = date(year, MONTHS[month_name], int(d))
        except ValueError:
            ambiguous, reason = True, "data_invalida"
        else:
            # Fara an explicit, o data deja trecuta se refera la anul urmator.
            if not y and candidate < today:
                candidate = candidate.replace(year=year + 1)
            day = candidate
            spans.append(match.span())

    # 5. Zi a saptamanii: „marți", „marți viitoare".
    match = _WEEKDAY.search(folded)
    if match and day is None:
        day = _next_weekday(today, WEEKDAYS[match.group(1)], force_next_week=bool(match.group(2)))
        spans.append(match.span())

    # 6. Ora exacta.
    part = _find_day_part(folded)
    match = _TIME_HHMM.search(folded)
    if match:
        at_time = time(int(match.group(1)), int(match.group(2)))
        spans.append(match.span())
    else:
        for pattern, minute in ((_TIME_HALF, 30), (_TIME_QUARTER, 15)):
            match = pattern.search(folded)
            if match and (hour := word_to_number(match.group(1))) is not None:
                at_time = time(hour % 24, minute)
                spans.append(match.span())
                break
        else:
            match = _TIME_HOUR.search(folded)
            hour = word_to_number(match.group(1) or match.group(2)) if match else None
            if match and hour is not None:
                # „la 3" fara alt indiciu poate insemna 03:00 sau 15:00.
                if part and part[0] >= time(12, 0) and hour < 12:
                    hour += 12
                elif hour < 7:
                    ambiguous, reason = True, "ora_ambigua"
                    hour += 12
                at_time = time(hour % 24, 0)
                spans.append(match.span())

    # 7. Parti de zi, daca nu avem ora exacta.
    if at_time is None and part is not None:
        at_time = part[0]
    if part is not None:
        spans.append(part[1])

    # 8. Ultima incercare: dateparser pe textul integral.
    if day is None and at_time is None:
        parsed = dateparser.parse(
            text,
            languages=["ro"],
            settings={
                "RELATIVE_BASE": now.replace(tzinfo=None),
                "PREFER_DATES_FROM": "future",
                "RETURN_AS_TIMEZONE_AWARE": False,
            },
        )
        if parsed is not None:
            day = parsed.date()
            if parsed.time() != time(0, 0):
                at_time = parsed.time().replace(second=0, microsecond=0)

    return TemporalMatch(
        day=day,
        at_time=at_time,
        spans=tuple(sorted(set(spans))),
        ambiguous=ambiguous,
        reason=reason,
    )


def strip_temporal(text: str, match: TemporalMatch) -> str:
    """Scoate fragmentele temporale din text, ca titlul sa nu contina „mâine la 10"."""
    return cut_spans(text, list(match.spans))


#: Cuvintele care semnaleaza o referinta la ZI, chiar daca `extract` nu reuseste
#: sa o transforme intr-o data. „mai" lipseste deliberat: ca luna apare doar dupa
#: un numar (deci este prinsa de `_DATE_MONTH`), iar ca adverb este mult mai frecvent.
_DATE_MARKER_WORDS = sorted(
    {
        *RELATIVE_DAYS,
        *WEEKDAYS,
        *(name for name in MONTHS if name != "mai"),
        "saptamana",
        "saptamani",
        "luna",
        "lunile",
        "anul",
        "weekend",
        "zi",
        "zile",
        "data",
    },
    key=len,
    reverse=True,
)
_DATE_MARKER = re.compile(r"\b(?:" + "|".join(_DATE_MARKER_WORDS) + r")\b")

#: Cuvintele care semnaleaza o referinta la ORA.
_TIME_MARKER_WORDS = sorted(
    {*DAY_PARTS, "ora", "orele", "diseara", "deseara", "amiaza", "pranz"},
    key=len,
    reverse=True,
)
_TIME_MARKER = re.compile(r"\b(?:" + "|".join(_TIME_MARKER_WORDS) + r")\b")

#: „peste doua ore" este si o ora, si o zi; „peste doua zile" este doar o zi.
_IN_N_HOURS = re.compile(r"\bpeste\s+(?:[a-z]+|\d+)\s+(?:minute?|ore?)\b")


def day_part(text: str) -> time | None:
    """Ora implicita a partii de zi rostite: „dimineața" → 09:00, „seara" → 19:00."""
    found = _find_day_part(fold(text))
    return found[0] if found else None


def has_explicit_hour(text: str) -> bool:
    """Textul contine o ora spusa ca atare, nu doar o parte de zi?"""
    folded = fold(text)
    return any(
        pattern.search(folded)
        for pattern in (_TIME_HHMM, _TIME_HALF, _TIME_QUARTER, _TIME_HOUR, _IN_N_HOURS)
    )


def has_date_marker(text: str) -> bool:
    """Textul contine vreo referinta la o zi, chiar daca nu poate fi interpretata?

    Face diferenta intre „nu s-a spus nimic despre zi" — caz in care o data venita
    de la model este inventata — si „s-a spus ceva ce nu stim sa citim", caz in
    care valoarea modelului merita pastrata, dar confirmata.
    """
    folded = fold(text)
    return bool(_DATE_MARKER.search(folded)) or any(
        pattern.search(folded) for pattern in (_DATE_NUMERIC, _DATE_MONTH, _IN_N_UNITS)
    )


def has_time_marker(text: str) -> bool:
    """Acelasi rationament, pentru ora."""
    folded = fold(text)
    return bool(_TIME_MARKER.search(folded)) or any(
        pattern.search(folded)
        for pattern in (_TIME_HHMM, _TIME_HALF, _TIME_QUARTER, _TIME_HOUR, _IN_N_HOURS)
    )


def has_temporal_marker(text: str) -> bool:
    return has_date_marker(text) or has_time_marker(text)
