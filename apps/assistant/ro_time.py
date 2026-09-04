"""Interpretarea expresiilor temporale in limba romana.

`dateparser` acopera bine formele scrise („6 septembrie 2026", „06.09.2026"), dar
vorbirea curenta foloseste expresii pe care le rezolvam explicit inainte:
„mâine dimineața", „marți viitoare", „peste două săptămâni", „la trei și jumătate".

Toate tiparele sunt scrise fara diacritice si se aplica pe versiunea „impaturita"
a textului (`normalize.fold`), aliniata caracter cu caracter cu originalul. Asa
putem taia exact fragmentele consumate, pastrand diacriticele in restul textului.

Principiul intregului modul: ce nu se poate citi fara echivoc nu se ghiceste. O
expresie neclara iese cu un motiv in `reasons`, iar stratul de deasupra o
transforma in intrebare.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
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


@dataclass(frozen=True)
class DayPart:
    """O parte de zi.

    Unele numesc un moment („la prânz" este 12:00) si pot fi folosite ca atare.
    Restul sunt perioade: „seara" acopera cinci ore, deci nu are voie sa devina
    tacit 19:00. Ele doar aseaza o ora rostita in jumatatea buna a zilei —
    „la trei după-amiaza" este 15:00, „la două dimineața" este 02:00 — iar cand
    ora lipseste cu totul, o cer.
    """

    label: str
    code: str
    #: Fereastra orara acoperita; se poate incheia inainte de a incepe („noaptea").
    window: tuple[int, int]
    #: Ora exacta, pentru partile care numesc un moment.
    exact: time | None = None

    @property
    def is_vague(self) -> bool:
        return self.exact is None

    def covers(self, hour: int) -> bool:
        start, end = self.window
        if start <= end:
            return start <= hour <= end
        return hour >= start or hour <= end

    def place(self, hour: int) -> int:
        """Aseaza o ora rostita in fereastra partii: 3 + „după-amiaza" = 15."""
        for candidate in (hour, (hour + 12) % 24):
            if self.covers(candidate):
                return candidate
        # In afara ferestrei („la două noaptea"): pastram jumatatea sugerata.
        if self.window[0] >= 12 and hour < 12:
            return hour + 12
        return hour


DAY_PARTS: dict[str, DayPart] = {
    "dimineata": DayPart("dimineața", "dimineata", window=(5, 11)),
    "dimineaza": DayPart("dimineața", "dimineata", window=(5, 11)),
    "la pranz": DayPart("la prânz", "pranz", window=(11, 13), exact=time(12, 0)),
    "amiaza": DayPart("amiază", "amiaza", window=(11, 13), exact=time(12, 0)),
    "dupa-amiaza": DayPart("după-amiaza", "dupa_amiaza", window=(12, 18)),
    "dupa amiaza": DayPart("după-amiaza", "dupa_amiaza", window=(12, 18)),
    "seara": DayPart("seara", "seara", window=(18, 23)),
    "noaptea": DayPart("noaptea", "noaptea", window=(21, 5)),
}

DAY_PART_BY_CODE = {part.code: part for part in DAY_PARTS.values()}

#: Prefixul motivului produs de o parte de zi rostita fara ora. Codul poarta cu el
#: partea, ca intrebarea sa fie „La ce oră după-amiaza?" si ca raspunsul „la trei"
#: sa poata fi asezat inapoi in aceeasi jumatate de zi.
VAGUE_HOUR_PREFIX = "ora_lipseste_"


def vague_hour_reason(part: DayPart) -> str:
    return VAGUE_HOUR_PREFIX + part.code


def part_from_reason(reason: str) -> DayPart | None:
    if not reason.startswith(VAGUE_HOUR_PREFIX):
        return None
    return DAY_PART_BY_CODE.get(reason[len(VAGUE_HOUR_PREFIX) :])

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

#: Sufixul AM/PM, scris in toate formele uzuale: „pm", „PM", „p.m.", „p. m.".
_AMPM_SUFFIX = r"\s*([ap])\.?\s?m\.?(?![a-z])"

_TIME_AMPM = re.compile(r"\b(?:la\s+|ora\s+|orele\s+)?(\d{1,2})(?:[:.,]([0-5]\d))?" + _AMPM_SUFFIX)
_TIME_HHMM = re.compile(r"\b(?:la\s+|ora\s+)?([01]?\d|2[0-3])[:.,]([0-5]\d)\b")
_TIME_HOUR = re.compile(
    r"\b(?:la|ora|orele)\s+(?:"
    r"(" + _HOUR_WORDS_ALT + r")\b" + _HOUR_WORD_TAIL + r"|"
    r"([01]?\d|2[0-3])\b(?![:.,]?\d)"
    r")"
)
_TIME_HALF = re.compile(r"\b(?:la|ora)\s+([a-z]+|\d{1,2})\s+si\s+jumatate\b")
_TIME_QUARTER = re.compile(r"\b(?:la|ora)\s+([a-z]+|\d{1,2})\s+si\s+un\s+sfert\b")

#: Un capat de interval: cifre cu sau fara minute si AM/PM, ori un numeral rostit.
_CLOCK = r"(?:\d{1,2}(?:[:.]\d{2})?(?:\s*[ap]\.?\s?m\.?)?|" + _HOUR_WORDS_ALT + r")"

#: „de la 10 la 12", „între 10 și 12", „de la 10 AM la 12 PM".
_RANGE_WORDS = re.compile(
    r"\b(?:de\s+la|intre)\s+(" + _CLOCK + r")\s+(?:pana\s+la|la|si)\s+(" + _CLOCK + r")"
    r"(?![a-z])"
)
#: „10–12", „10:30–12:45" — linia en/em nu apare niciodata intr-o data scrisa.
_RANGE_DASH = re.compile(r"\b(" + _CLOCK + r")\s*[–—]\s*(" + _CLOCK + r")(?![a-z])")
#: Cratima simpla, dar numai cand minutele fac citirea neechivoca: „10:30-12:45".
_RANGE_HYPHEN_EXACT = re.compile(r"\b(\d{1,2}[:.]\d{2})\s*-\s*(\d{1,2}[:.]\d{2})\b")
#: Cratima simpla intre doua numere mici, fara minute si fara an: „10-12". Poate fi
#: si interval, si data. Nu o decidem noi.
_HYPHEN_PAIR = re.compile(r"\b(\d{1,2})\s*-\s*(\d{1,2})\b(?![\s]*[-./]\s*\d)")

_FRAGMENT_AMPM = re.compile(r"(\d{1,2})(?:[:.](\d{2}))?" + _AMPM_SUFFIX)
_FRAGMENT_HHMM = re.compile(r"(\d{1,2})[:.](\d{2})")

_DATE_NUMERIC = re.compile(r"\b(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?\b")
_DATE_MONTH = re.compile(r"\b(?:pe\s+)?(\d{1,2})\s+(" + "|".join(MONTHS) + r")\b(?:\s+(\d{4}))?")
_IN_N_UNITS = re.compile(r"\bpeste\s+([a-z]+|\d+)\s+(minute?|ore?|zile?|saptamani?|luni)\b")
_WEEKDAY = re.compile(
    r"\b(?:in\s+|pe\s+)?(" + "|".join(WEEKDAYS) + r")\b(\s+viitoare|\s+viitor)?"
)
#: „săptămâna viitoare" fara nicio zi: stim saptamana, nu si ziua.
_NEXT_WEEK = re.compile(r"\bsaptamana\s+(?:viitoare|urmatoare)\b")


@dataclass(frozen=True)
class TemporalMatch:
    day: date | None = None
    at_time: time | None = None
    end_time: time | None = None
    #: Intervalele consumate din text, ca sa nu ramana in titlu.
    spans: tuple[tuple[int, int], ...] = ()
    #: Motivele pentru care citirea nu este sigura. Politica le transforma in intrebari.
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def has_value(self) -> bool:
        return self.day is not None or self.at_time is not None

    @property
    def ambiguous(self) -> bool:
        return bool(self.reasons)

    @property
    def reason(self) -> str:
        """Primul motiv. Pastrat pentru apelantii care asteapta un singur cod."""
        return self.reasons[0] if self.reasons else ""


def word_to_number(word: str) -> int | None:
    word = word.strip()
    if word.isdigit():
        return int(word)
    return NUMBER_WORDS.get(word)


def _ampm_to_hour(hour: int, marker: str) -> int | None:
    """12 AM este miezul noptii, 12 PM este amiaza — singurele doua exceptii."""
    if not 1 <= hour <= 12:
        return None
    if marker == "a":
        return 0 if hour == 12 else hour
    return 12 if hour == 12 else hour + 12


def _next_weekday(reference: date, weekday: int, *, force_next_week: bool) -> date:
    delta = (weekday - reference.weekday()) % 7
    if delta == 0:
        delta = 7
    if force_next_week:
        delta += 7
    return reference + timedelta(days=delta)


def weekday_next_week(reference: date, weekday: int) -> date:
    """Ziua cu acest nume din saptamana urmatoare celei curente.

    „Săptămâna viitoare" plus „miercuri" nu inseamna prima miercuri de acum, ci
    miercurea din saptamana de dupa cea in care ne aflam.
    """
    monday_next = reference + timedelta(days=7 - reference.weekday())
    return monday_next + timedelta(days=weekday)


def _find_day_part(folded: str) -> tuple[DayPart, tuple[int, int]] | None:
    """Cauta partile de zi, cele mai lungi intai.

    Ordinea conteaza: „amiaza" este continut in „dupa-amiaza". Cautat primul, ar
    da 12:00 acolo unde s-a spus 15:00, si ar taia din text doar jumatatea a doua.
    """
    for word in sorted(DAY_PARTS, key=len, reverse=True):
        index = folded.find(word)
        if index != -1:
            return DAY_PARTS[word], (index, index + len(word))
    return None


def _clock_from_fragment(fragment: str, part: DayPart | None) -> tuple[time | None, bool]:
    """Citeste un capat de interval. Al doilea element spune daca ora e ambigua."""
    fragment = fragment.strip()
    match = _FRAGMENT_AMPM.fullmatch(fragment)
    if match:
        hour = _ampm_to_hour(int(match.group(1)), match.group(3))
        return (time(hour, int(match.group(2) or 0)), False) if hour is not None else (None, False)

    match = _FRAGMENT_HHMM.fullmatch(fragment)
    if match and int(match.group(1)) <= 23:
        return time(int(match.group(1)), int(match.group(2))), False

    hour = word_to_number(fragment)
    if hour is None or hour > 23:
        return None, False
    if part is not None:
        return time(part.place(hour) % 24, 0), False
    # „la 3" fara alt indiciu poate insemna 03:00 sau 15:00.
    if hour < 7:
        return time((hour + 12) % 24, 0), True
    return time(hour, 0), False


def _find_range(folded: str, part: DayPart | None):
    """Primul interval orar din text, cautat inaintea oricarei ore singulare."""
    for pattern in (_RANGE_WORDS, _RANGE_DASH, _RANGE_HYPHEN_EXACT):
        match = pattern.search(folded)
        if not match:
            continue
        start, start_vague = _clock_from_fragment(match.group(1), part)
        end, end_vague = _clock_from_fragment(match.group(2), part)
        if start is None or end is None:
            continue
        return start, end, match.span(), (start_vague or end_vague)
    return None


def _overlaps(span: tuple[int, int], taken: list[tuple[int, int]]) -> bool:
    return any(span[0] < end and start < span[1] for start, end in taken)


def extract(text: str, *, now: datetime) -> TemporalMatch:
    """Extrage data, ora si intervalul dintr-o comanda. Ce nu e clar ramane None."""
    folded = fold(text)
    today = now.date()
    spans: list[tuple[int, int]] = []
    day: date | None = None
    at_time: time | None = None
    end_time: time | None = None
    reasons: list[str] = []

    part_found = _find_day_part(folded)
    part = part_found[0] if part_found else None

    # 1. Intervalul orar, inaintea oricarei alte reguli: „10-12" ar fi citit altfel
    #    ca 10 decembrie, iar „de la 10 la 12" ca ora 10 si atat.
    found = _find_range(folded, part)
    if found is not None:
        at_time, end_time, span, vague = found
        spans.append(span)
        if vague:
            reasons.append("ora_ambigua")
        if end_time <= at_time:
            # Nu presupunem trecerea in ziua urmatoare: intrebam.
            end_time = None
            reasons.append("interval_invalid")

    # 2. Cratima intre doua numere mici ramane nedecisa: si interval, si data.
    if at_time is None:
        pair = _HYPHEN_PAIR.search(folded)
        if pair and not _overlaps(pair.span(), spans):
            reasons.append("interval_sau_data")
            spans.append(pair.span())

    # 3. Zile relative: azi / mâine / poimâine (cele mai lungi intai).
    for word, offset in RELATIVE_DAYS.items():
        match = re.search(rf"\b{word}\b", folded)
        if match:
            day = today + timedelta(days=offset)
            spans.append(match.span())
            break

    # 4. „peste N zile / ore / săptămâni".
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

    # 5. Data numerica: 06.09.2026.
    match = _DATE_NUMERIC.search(folded)
    if match and day is None and not _overlaps(match.span(), spans):
        d, m, y = match.groups()
        year = today.year if y is None else (2000 + int(y) if len(y) == 2 else int(y))
        try:
            day = date(year, int(m), int(d))
            spans.append(match.span())
        except ValueError:
            reasons.append("data_invalida")

    # 6. „6 septembrie" / „6 septembrie 2026".
    match = _DATE_MONTH.search(folded)
    if match and day is None:
        d, month_name, y = match.groups()
        year = int(y) if y else today.year
        try:
            candidate = date(year, MONTHS[month_name], int(d))
        except ValueError:
            reasons.append("data_invalida")
        else:
            # Fara an explicit, o data deja trecuta se refera la anul urmator.
            if not y and candidate < today:
                candidate = candidate.replace(year=year + 1)
            day = candidate
            spans.append(match.span())

    # 7. Zi a saptamanii: „marți", „marți viitoare".
    match = _WEEKDAY.search(folded)
    if match and day is None:
        day = _next_weekday(today, WEEKDAYS[match.group(1)], force_next_week=bool(match.group(2)))
        spans.append(match.span())
    elif match is None and day is None:
        # „Săptămâna viitoare" fara nicio zi: stim saptamana, nu si ziua.
        next_week = _NEXT_WEEK.search(folded)
        if next_week:
            reasons.append("zi_saptamana_lipseste")
            spans.append(next_week.span())

    # 8. Ora exacta, daca nu am citit deja un interval.
    if at_time is None:
        at_time, hour_reason, hour_span = _find_single_time(folded, part)
        if hour_reason:
            reasons.append(hour_reason)
        if hour_span:
            spans.append(hour_span)

    # 9. Partea de zi. Una care numeste un moment („la prânz") tine loc de ora; una
    #    vaga („seara") nu inventeaza nimic, ci cere ora.
    if part_found is not None:
        spans.append(part_found[1])
        if at_time is None:
            if part.exact is not None:
                at_time = part.exact
            else:
                reasons.append(vague_hour_reason(part))

    # 10. Ultima incercare: dateparser pe textul integral.
    if day is None and at_time is None and not reasons:
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
        end_time=end_time,
        spans=tuple(sorted(set(spans))),
        reasons=tuple(dict.fromkeys(reasons)),
    )


def _find_single_time(
    folded: str, part: DayPart | None
) -> tuple[time | None, str, tuple[int, int] | None]:
    """O singura ora rostita, in ordinea increderii: AM/PM, HH:MM, sferturi, ora."""
    match = _TIME_AMPM.search(folded)
    if match:
        hour = _ampm_to_hour(int(match.group(1)), match.group(3))
        if hour is not None:
            # AM/PM spus explicit nu mai are nevoie de nicio dezambiguizare.
            return time(hour, int(match.group(2) or 0)), "", match.span()

    match = _TIME_HHMM.search(folded)
    if match:
        return time(int(match.group(1)), int(match.group(2))), "", match.span()

    for pattern, minute in ((_TIME_HALF, 30), (_TIME_QUARTER, 15)):
        match = pattern.search(folded)
        if match and (hour := word_to_number(match.group(1))) is not None:
            return time(hour % 24, minute), "", match.span()

    match = _TIME_HOUR.search(folded)
    hour = word_to_number(match.group(1) or match.group(2)) if match else None
    if match and hour is not None:
        if part is not None:
            return time(part.place(hour) % 24, 0), "", match.span()
        if hour < 7:
            return time((hour + 12) % 24, 0), "ora_ambigua", match.span()
        return time(hour, 0), "", match.span()

    return None, "", None


def strip_temporal(text: str, match: TemporalMatch) -> str:
    """Scoate fragmentele temporale din text, ca titlul sa nu contina „mâine la 10"."""
    return cut_spans(text, list(match.spans))


def weekday_from_text(text: str) -> int | None:
    """Indexul zilei saptamanii rostite („miercuri" -> 2), daca apare vreuna."""
    folded = fold(text)
    for name, index in WEEKDAYS.items():
        if re.search(rf"\b{name}\b", folded):
            return index
    return None


def day_part(text: str) -> DayPart | None:
    """Partea de zi rostita, daca exista."""
    found = _find_day_part(fold(text))
    return found[0] if found else None


#: Formulele care anunta un interval, chiar daca orele lui nu pot fi citite.
_RANGE_MARKER = re.compile(r"\b(?:de\s+la|intre|pana\s+la)\b|[–—]")


def has_range_marker(text: str) -> bool:
    """Textul vorbeste despre un interval?

    O ora de final se sustine doar pe o formulare de interval. „Mă întâlnesc mâine
    la 10" contine o ora, dar nimic care sa justifice un final.
    """
    folded = fold(text)
    return bool(_RANGE_MARKER.search(folded)) or any(
        pattern.search(folded)
        for pattern in (_RANGE_WORDS, _RANGE_DASH, _RANGE_HYPHEN_EXACT)
    )


def has_ampm(text: str) -> bool:
    """Textul spune explicit AM sau PM? Atunci nu mai are nevoie de dezambiguizare."""
    return bool(_TIME_AMPM.search(fold(text)))


def has_explicit_hour(text: str) -> bool:
    """Textul contine o ora spusa ca atare, nu doar o parte de zi?"""
    folded = fold(text)
    return any(
        pattern.search(folded)
        for pattern in (_TIME_AMPM, _TIME_HHMM, _TIME_HALF, _TIME_QUARTER, _TIME_HOUR)
    )


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
        for pattern in (
            _TIME_AMPM,
            _TIME_HHMM,
            _TIME_HALF,
            _TIME_QUARTER,
            _TIME_HOUR,
            _IN_N_HOURS,
            _RANGE_WORDS,
            _RANGE_DASH,
            _RANGE_HYPHEN_EXACT,
        )
    )


def has_temporal_marker(text: str) -> bool:
    return has_date_marker(text) or has_time_marker(text)
