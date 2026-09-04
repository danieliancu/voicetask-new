"""Parser de intentii bazat pe reguli, in limba romana.

Acesta este providerul implicit: aplicatia trebuie sa functioneze complet fara
nicio cheie API. Nu este un stub — recunoaste verbele uzuale, extrage titlul,
data, ora, locatia si persoana, si semnaleaza singur ce a ramas ambiguu.

Toate tiparele sunt scrise fara diacritice si se aplica pe versiunea „impaturita"
(`normalize.fold`), aliniata caracter cu caracter cu textul original. Fragmentele
consumate se taie din original, deci titlul pastreaza diacriticele rostite.
"""

from __future__ import annotations

import re

from apps.assistant import ro_time
from apps.assistant.schemas import Intent
from apps.core.providers.base import IntentParserProvider
from apps.core.providers.context import IntentContext
from apps.search.normalize import cut_spans, fold

# Verbele care declanseaza fiecare intentie, in ordinea in care sunt testate.
INTENT_PATTERNS: tuple[tuple[Intent, tuple[str, ...]], ...] = (
    (
        Intent.DELETE_ITEM,
        (r"\bsterge\b", r"\bstergeti\b", r"\banuleaza\b", r"\brenunta la\b", r"\barunca\b"),
    ),
    (
        Intent.UPDATE_ITEM,
        (
            r"\bmodifica\b",
            r"\bschimba\b",
            r"\bmuta\b",
            r"\bactualizeaza\b",
            r"\bamana\b",
            r"\breprogrameaza\b",
        ),
    ),
    (
        Intent.FOLLOW_UP_EMAIL,
        (
            r"\burmareste\s+(?:e-?mail|mesaj)",
            r"\brevino la\s+(?:e-?mail|mesaj)",
            r"\be-?mail(?:ul)?\s+(?:de la|catre)\b",
        ),
    ),
    (
        Intent.CREATE_REMINDER,
        (
            r"\balarm[ae]\b",
            r"\baminteste\b",
            r"\bmemento\b",
            r"\bnu uita\b",
            r"\bsa nu uit\b",
            r"\bda-mi de stire\b",
            r"\btrezeste-ma\b",
        ),
    ),
    (
        Intent.CREATE_APPOINTMENT,
        (
            r"\bprogramar[ei]\b",
            r"\bprogrameaza\b",
            r"\bintalnire\b",
            # Formele fara verb de comanda: „Mă întâlnesc mâine cu Ion" este o
            # programare la fel de mult ca „Programează o întâlnire cu Ion".
            r"\bma intalnesc\b",
            r"\bne intalnim\b",
            r"\bma vad\b",
            r"\bne vedem\b",
            r"\bsedinta\b",
            r"\beveniment\b",
            r"\bconsultatie\b",
            r"\bcontrol (?:medical|la)\b",
            r"\bzbor\b",
            r"\bvizita la\b",
            r"\brezervare\b",
        ),
    ),
    (
        Intent.SEARCH,
        (
            r"\bcauta\b",
            r"\bgaseste\b",
            r"\bunde (?:este|e|am)\b",
            r"\barata-mi\b",
            r"\bcare (?:este|e)\b",
        ),
    ),
    (
        Intent.CREATE_NOTE,
        (
            r"\bnoteaza\b",
            r"\bnotit[ae]\b",
            r"\bscrie\b",
            r"\bretine\b",
            r"\bidee\b",
            r"\blista de\b",
        ),
    ),
)

#: Formulele de politete si de intentie care preced comanda propriu-zisa.
LEADING_NOISE = re.compile(
    r"^(?:te rog|va rog|hai|haide|asistent|vreau sa|as vrea sa|as dori sa|poti sa|poti)\b[\s,]*"
)

#: „cu titlul X", „intitulata X" — tot ce urmeaza este titlul.
TITLE_MARKER = re.compile(
    r"\b(?:cu\s+titlul|cu\s+numele|intitulat[ae]?|numit[ae]?|denumit[ae]?)\s+"
)

#: Verbul de comanda de la inceputul frazei.
VERB_PREFIX = re.compile(
    r"^(?:noteaza|scrie|salveaza|retine|creeaza|adauga|pune(?:-mi)?|fa(?:-mi)?|"
    r"programeaza(?:-mi)?|aminteste(?:-mi)?|seteaza|sterge|modifica|schimba|muta|"
    r"cauta|gaseste|arata(?:-mi)?|urmareste)\b[\s,]*"
)

#: Articole si prepozitii fara continut, mereu sigure de taiat.
ARTICLE_PREFIX = re.compile(
    r"^(?:o|un|imi|mi|ca|sa|de|la|in|pe|cu|pentru|ceva|urmatoarea|urmatorul)\b[\s,]*"
)

#: Substantivele de domeniu. Se taie NUMAI daca fraza a inceput cu un verb de
#: comanda — altfel „Ședință cu părinții" si-ar pierde chiar subiectul.
DOMAIN_NOUN_PREFIX = re.compile(
    r"^(?:notita|notite|alarma|alarme|memento|programare|programarea|programari|"
    r"intalnire|intalnirea|sedinta|eveniment|evenimentul|emailul|e-?mail|mesajul)\b[\s,]*"
)

#: Formulele care, dupa ce li se scot data si ora, nu mai lasa nimic folositor in
#: titlu. „Mă întâlnesc vineri la 3" ar da titlul „Mă întâlnesc" — un verb, nu o
#: eticheta. Fiecare primeste numele lucrului despre care este vorba, iar restul
#: frazei („cu Ion") se pastreaza dupa el.
#:
#: „Programare" si „Ședință" lipsesc din prima pozitie deliberat: acolo textul de
#: dupa verb este chiar subiectul („Programare la dentist") si nu trebuie inlocuit.
CANONICAL_TITLES = (
    (re.compile(r"^(?:am\s+)?(?:un\s+)?control(?:\s+medical)?\b"), "Control medical"),
    (re.compile(r"^(?:ma\s+intalnesc|ne\s+intalnim|ma\s+vad|ne\s+vedem)\b"), "Întâlnire"),
    (re.compile(r"^(?:am\s+)?(?:o\s+)?intalnire\b"), "Întâlnire"),
    (re.compile(r"^(?:am\s+)?(?:o\s+)?consultatie\b"), "Consultație"),
)

#: Resturi de prepozitii ramase la finalul titlului dupa taierea datei sau orei.
TRAILING_NOISE = re.compile(r"[\s,]*\b(?:la|in|pe|de|cu|si|ora|pentru|ca)\b[\s,.:;-]*$")

LOCATION_PLACE = re.compile(
    r"\b(?:la|in|pe)\s+((?:clinica|spitalul|scoala|liceul|gradinita|hotelul|restaurantul|"
    r"aeroportul|cabinetul|sediul|biroul|sala|strada|bulevardul)"
    # Numele locului se opreste la primul cuvant functional: fara oprire,
    # „la clinica Regina Maria la ora 9" ar da locatia „clinica Regina Maria la ora".
    r"(?:\s+(?!(?:la|in|pe|de|cu|si|ora|orele|pentru|maine|azi|poimaine|dimineata|"
    r"seara|amiaza|noaptea|numarul|nr)\b)[\w.-]+){1,4}"
    # Numarul face parte din adresa, nu din titlu: „strada Covaci, numarul 4".
    r"(?:,?\s+(?:numarul|nr\.?)\s*\d+[a-z]?)?)"
)
LOCATION_ONLINE = re.compile(r"\b(google meet|zoom|teams|skype)\b")

PERSON = re.compile(r"\b(?:de la|catre|cu|pentru)\s+([A-ZĂÂÎȘȚ][\w-]+(?:\s+[A-ZĂÂÎȘȚ][\w-]+)?)")

AMOUNT = re.compile(r"\b(\d{1,3}(?:[ .]\d{3})*(?:[,.]\d{1,2})?)\s*(lei|ron|eur|euro|£|\$|usd)\b")

CURRENCY_MAP = {
    "lei": "lei",
    "ron": "lei",
    "eur": "EUR",
    "euro": "EUR",
    "£": "GBP",
    "$": "USD",
    "usd": "USD",
}

OFFSET_PATTERNS = (
    (re.compile(r"\bcu\s+(\d+|o|doua|trei)\s+zi(?:le)?\s+inainte\b"), 1440),
    (re.compile(r"\bcu\s+(\d+|o|doua|trei)\s+or[ae]\s+inainte\b"), 60),
    (re.compile(r"\bcu\s+(\d+)\s+(?:de\s+)?minute\s+inainte\b"), 1),
)


#: Increderea unei potriviri pe verb explicit. Stratul de reconciliere o foloseste
#: ca prag: numai o intentie ancorata intr-un verb rostit poate corecta modelul.
VERB_SCORE = 0.9


def detect_intent(folded: str, context: IntentContext) -> tuple[Intent, float]:
    """Intentia dedusa determinist din verbele rostite.

    Scoasa din clasa ca `reconcile` sa poata confrunta raspunsul modelului cu
    aceeasi detectie, fara sa instantieze un parser intreg.
    """
    for intent, patterns in INTENT_PATTERNS:
        for pattern in patterns:
            if re.search(pattern, folded):
                return intent, VERB_SCORE
    # In modul de editare, o comanda fara verb explicit inseamna modificare.
    if context.mode == "edit":
        return Intent.UPDATE_ITEM, 0.6
    # Fara verb, dar cu o data clara: cel mai probabil o programare.
    if ro_time.extract(folded, now=context.now).day is not None:
        return Intent.CREATE_APPOINTMENT, 0.45
    return Intent.CREATE_NOTE, 0.4


class RuleBasedIntentParser(IntentParserProvider):
    """Interpretare deterministica: acelasi text da mereu acelasi rezultat."""

    name = "reguli-ro"
    # Este o implementare reala, doar ca nu foloseste un serviciu extern.
    is_mock = False

    def parse(self, text: str, *, context: IntentContext) -> dict:
        raw = (text or "").strip()
        if not raw:
            return {"intent": Intent.UNKNOWN, "confidence": 0.0}

        folded = fold(raw)
        intent, verb_score = detect_intent(folded, context)
        temporal = ro_time.extract(raw, now=context.now)
        ambiguity: list[str] = []

        if temporal.ambiguous:
            ambiguity.append(temporal.reason or "data_ambigua")

        payload: dict = {
            "intent": intent,
            "date": temporal.day,
            "start_time": temporal.at_time,
        }

        location, location_span = self._location(folded, raw)
        if location:
            payload["location"] = location

        offset, offset_span = self._offset(folded)
        body = self._body(raw, temporal, location_span, offset_span)

        if intent == Intent.SEARCH:
            payload["search_query"] = self._title(body) or body or raw
            payload["title"] = None
        else:
            payload["title"] = self._title(body) or None

        person = self._person(raw)
        if person:
            payload["person"] = person

        amount, currency = self._amount(folded)
        if amount is not None:
            payload["amount"] = amount
            payload["currency"] = currency

        if offset is not None:
            payload["reminder_offset"] = offset
        elif intent == Intent.CREATE_APPOINTMENT:
            payload["reminder_offset"] = context.default_reminder_offset

        if intent in {Intent.UPDATE_ITEM, Intent.DELETE_ITEM}:
            payload["target_kind"] = context.target_kind
            payload["target_id"] = context.target_id
            if context.target_id is None:
                ambiguity.append("tinta_nespecificata")

        if intent in {Intent.CREATE_APPOINTMENT, Intent.CREATE_REMINDER} and temporal.day is None:
            ambiguity.append("data_lipseste")

        payload["confidence"] = self._confidence(intent, verb_score, payload, ambiguity)
        payload["ambiguity"] = ambiguity
        return payload

    # ------------------------------------------------------------------ intern

    def _body(self, raw: str, temporal, location_span, offset_span) -> str:
        """Textul ramas dupa scoaterea datei, orei, locatiei si decalajului extrase."""
        spans = list(temporal.spans)
        for span in (location_span, offset_span):
            if span:
                spans.append(span)
        return cut_spans(raw, spans)

    def _title(self, body: str) -> str:
        """Curata verbul de comanda si umplutura, pastrand diacriticele."""
        if not body:
            return ""

        # Marcajul explicit de titlu are prioritate: tot ce urmeaza este titlul.
        marker = TITLE_MARKER.search(fold(body))
        if marker:
            body = body[marker.end() :].strip(" ,.-")

        canonical = self._canonical_title(body)
        if canonical is not None:
            return canonical

        had_verb = False
        previous = None
        while previous != body and body:
            previous = body
            body = body.lstrip(" ,.:;-")
            for pattern in (LEADING_NOISE, VERB_PREFIX, ARTICLE_PREFIX):
                match = pattern.match(fold(body))
                if match:
                    if pattern is VERB_PREFIX:
                        had_verb = True
                    body = body[match.end() :].lstrip()
            if had_verb:
                match = DOMAIN_NOUN_PREFIX.match(fold(body))
                if match:
                    body = body[match.end() :].lstrip()
        body = TRAILING_NOISE.sub("", body).strip(" ,.-:;")

        # Pastram doar prima propozitie ca titlu.
        title = re.split(r"[.;]\s", body, maxsplit=1)[0].strip(" ,.-:;")
        if len(title) > 200:
            title = title[:197].rsplit(" ", 1)[0] + "…"
        if title and title[0].islower():
            title = title[0].upper() + title[1:]
        return title

    def _canonical_title(self, body: str) -> str | None:
        """Eticheta pentru formulele care altfel ar lasa in titlu doar verbul."""
        leading = " ,.:;-"
        offset = len(body) - len(body.lstrip(leading))
        folded = fold(body)[offset:]
        for pattern, label in CANONICAL_TITLES:
            match = pattern.match(folded)
            if match is None:
                continue
            rest = body[offset + match.end() :]
            rest = TRAILING_NOISE.sub("", rest).strip(" ,.-:;")
            return f"{label} {rest}".strip() if rest else label
        return None

    def _location(self, folded: str, raw: str) -> tuple[str | None, tuple[int, int] | None]:
        match = LOCATION_ONLINE.search(folded)
        if match:
            return raw[match.start() : match.end()].title(), match.span()
        match = LOCATION_PLACE.search(folded)
        if match:
            value = raw[match.start(1) : match.end(1)].strip(" ,.")
            return value, match.span()
        return None, None

    def _person(self, raw: str) -> str | None:
        match = PERSON.search(raw)
        return match.group(1).strip() if match else None

    def _amount(self, folded: str) -> tuple[float | None, str | None]:
        match = AMOUNT.search(folded)
        if not match:
            return None, None
        number = match.group(1).replace(" ", "")
        if "," in number:
            number = number.replace(".", "").replace(",", ".")
        try:
            value = float(number)
        except ValueError:
            return None, None
        return value, CURRENCY_MAP.get(match.group(2), match.group(2))

    def _offset(self, folded: str) -> tuple[int | None, tuple[int, int] | None]:
        for pattern, unit_minutes in OFFSET_PATTERNS:
            match = pattern.search(folded)
            if match:
                count = ro_time.word_to_number(match.group(1)) or 1
                return count * unit_minutes, match.span()
        return None, None

    def _confidence(
        self, intent: Intent, verb_score: float, payload: dict, ambiguity: list[str]
    ) -> float:
        if intent == Intent.UNKNOWN:
            return 0.0
        score = verb_score
        if payload.get("title") or payload.get("search_query"):
            score += 0.05
        if payload.get("date"):
            score += 0.05
        score -= 0.2 * len(ambiguity)
        return max(0.0, min(1.0, round(score, 2)))
