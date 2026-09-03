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

_TIME_HHMM = re.compile(r"\b(?:la\s+|ora\s+)?([01]?\d|2[0-3])[:.,]([0-5]\d)\b")
_TIME_HOUR = re.compile(r"\b(?:la|ora)\s+([01]?\d|2[0-3])\b(?![:.,]?\d)")
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
    for word, value in DAY_PARTS.items():
        index = folded.find(word)
        if index != -1:
            return value, (index, index + len(word))
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
            if match:
                hour = int(match.group(1))
                # „la 3" fara alt indiciu poate insemna 03:00 sau 15:00.
                if part and part[0] >= time(12, 0) and hour < 12:
                    hour += 12
                elif hour < 7:
                    ambiguous, reason = True, "ora_ambigua"
                    hour += 12
                at_time = time(hour, 0)
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
