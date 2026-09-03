"""Extragerea structurata din textul recunoscut.

Fiecare camp are o valoare si un scor de incredere. Increderea combina:
- increderea OCR pe randul din care provine valoarea;
- cat de explicita a fost eticheta („TOTAL DE PLATĂ" > un numar gasit oriunde).

Campurile sub pragul din setari sunt marcate in formular ca „de verificat".
Nimic nu se transforma automat in alarma sau programare.
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass, field
from datetime import date, time

from apps.documents.pipeline import patterns
from apps.search.normalize import normalize

#: Cat de mult conteaza o eticheta explicita in scorul final.
LABEL_BONUS = 0.25
NO_LABEL_PENALTY = 0.35


@dataclass
class Field:
    value: object
    confidence: float
    #: Randul din care provine, pentru a arata contextul in interfata.
    evidence: str = ""

    def as_dict(self) -> dict:
        value = self.value
        if isinstance(value, (date, time)):
            value = value.isoformat()
        return {
            "value": value,
            "confidence": round(float(self.confidence), 3),
            "evidence": self.evidence[:120],
        }


@dataclass
class Extraction:
    fields: dict[str, Field] = field(default_factory=dict)
    document_type: str = "other"
    title: str = ""

    def as_dict(self) -> dict:
        return {name: item.as_dict() for name, item in self.fields.items()}

    def set(self, name: str, value, confidence: float, evidence: str = "") -> None:
        if value is None:
            return
        existing = self.fields.get(name)
        if existing is None or confidence > existing.confidence:
            self.fields[name] = Field(value, confidence, evidence)


@dataclass
class Line:
    raw: str
    normalized: str
    confidence: float


def _lines(text: str, ocr_lines) -> list[Line]:
    if ocr_lines:
        return [
            Line(raw=item.text, normalized=normalize(item.text), confidence=item.confidence)
            for item in ocr_lines
            if item.text.strip()
        ]
    return [
        Line(raw=raw, normalized=normalize(raw), confidence=0.7)
        for raw in text.splitlines()
        if raw.strip()
    ]


def _parse_date(text: str, *, prefer_future_year: bool = False) -> date | None:
    match = patterns.DATE_NUMERIC.search(text)
    if match:
        day, month, year = match.groups()
        year_value = int(year)
        if year_value < 100:
            year_value += 2000
        try:
            return date(year_value, int(month), int(day))
        except ValueError:
            return None
    match = patterns.DATE_TEXT.search(text)
    if match:
        day, month_name, year = match.groups()
        month = patterns.MONTHS.get(month_name)
        if month is None:
            return None
        year_value = int(year) if year else date.today().year
        try:
            parsed = date(year_value, month, int(day))
        except ValueError:
            return None
        if not year and prefer_future_year and parsed < date.today():
            parsed = parsed.replace(year=year_value + 1)
        return parsed
    return None


def _parse_amount(text: str, *, require_currency: bool = False) -> tuple[float, str] | None:
    if require_currency:
        match = patterns.AMOUNT_WITH_CURRENCY.search(text)
        if not match:
            return None
        number = (match.group("number1") or match.group("number2") or "").replace(" ", "")
        if "," in number:
            number = number.replace(".", "").replace(",", ".")
        try:
            value = float(number)
        except ValueError:
            return None
        marker = re.search(patterns.CURRENCY_ALTERNATIVES, match.group(0), re.IGNORECASE)
        currency = patterns.CURRENCY_MAP.get(marker.group(0).lower(), "") if marker else ""
        return value, currency

    match = patterns.AMOUNT.search(text)
    if not match:
        return None
    number = match.group("number").replace(" ", "")
    # „1.234,56" -> 1234.56 ; „84,20" -> 84.20 ; „84.20" -> 84.20
    if "," in number:
        number = number.replace(".", "").replace(",", ".")
    try:
        value = float(number)
    except ValueError:
        return None
    marker = (match.group("before") or match.group("after") or "").strip().lower()
    currency = patterns.CURRENCY_MAP.get(marker, "")
    return value, currency


def _has_label(normalized: str, labels: tuple[str, ...]) -> bool:
    """Cauta eticheta si pe varianta fara spatii a randului.

    Motoarele OCR antrenate pe alte limbi returneaza frecvent „DATALIMITADEPLATA"
    in loc de „DATA LIMITA DE PLATA".
    """
    collapsed = normalized.replace(" ", "")
    return any(
        re.search(pattern, normalized) or re.search(pattern, collapsed) for pattern in labels
    )


def _neighbourhood(lines: list[Line], index: int, span: int = 2) -> list[Line]:
    """Eticheta si valoarea sunt adesea pe randuri diferite in documentele scanate."""
    return lines[index : index + span + 1]


def detect_type(lines: list[Line]) -> tuple[str, float]:
    # Indiciile se cauta pe textul fara spatii, ca sa functioneze si pe randurile
    # lipite pe care le returneaza motoarele antrenate pe alte limbi.
    haystack = "".join(line.normalized.replace(" ", "") for line in lines)
    best, best_score = "other", 0.0
    for doc_type, hints in patterns.TYPE_HINTS:
        score = sum(1 for hint in hints if hint in haystack) / len(hints)
        if score > best_score:
            best, best_score = doc_type, score
    return best, min(1.0, best_score + 0.3 if best_score else 0.0)


def guess_title(lines: list[Line], document_type: str) -> str:
    """Titlul: prima linie semnificativa, curatata de zgomot."""
    for line in lines[:8]:
        text = line.raw.strip(" .:-")
        if len(text) < 4 or text.isdigit():
            continue
        if any(word in line.normalized for word in ("seria", "cui", "cif", "pagina")):
            continue
        words = text.split()
        if len(words) > 8:
            text = " ".join(words[:8])
        return text[:1].upper() + text[1:].lower() if text.isupper() else text
    return {
        "invoice": "Factură",
        "invitation": "Invitație",
        "medical": "Document medical",
        "receipt": "Bon fiscal",
        "letter": "Scrisoare",
    }.get(document_type, "Document scanat")


def extract(text: str, ocr_lines=None) -> Extraction:
    lines = _lines(text, ocr_lines)
    result = Extraction()
    if not lines:
        return result

    document_type, type_confidence = detect_type(lines)
    result.document_type = document_type
    result.set("document_type", document_type, type_confidence)
    result.title = guess_title(lines, document_type)
    result.set("title", result.title, 0.6 if result.title else 0.0, lines[0].raw)

    for index, line in enumerate(lines):
        window = _neighbourhood(lines, index)
        window_raw = " ".join(item.raw for item in window)

        # Data limita de plata.
        if _has_label(line.normalized, patterns.DUE_DATE_LABELS):
            parsed = _parse_date(window_raw, prefer_future_year=True)
            if parsed:
                result.set(
                    "due_date", parsed, min(1.0, line.confidence + LABEL_BONUS), window_raw
                )

        # Data documentului.
        if _has_label(line.normalized, patterns.DOCUMENT_DATE_LABELS):
            parsed = _parse_date(window_raw)
            if parsed:
                result.set(
                    "document_date", parsed, min(1.0, line.confidence + LABEL_BONUS), window_raw
                )

        # Data unui eveniment (invitatii).
        if _has_label(line.normalized, patterns.EVENT_DATE_LABELS) or document_type == "invitation":
            parsed = _parse_date(window_raw, prefer_future_year=True)
            if parsed:
                result.set(
                    "event_date", parsed, min(1.0, line.confidence + LABEL_BONUS * 0.5), window_raw
                )

        # Suma totala.
        if _has_label(line.normalized, patterns.TOTAL_LABELS):
            parsed = _parse_amount(window_raw)
            if parsed:
                amount, currency = parsed
                confidence = min(1.0, line.confidence + LABEL_BONUS)
                result.set("amount", amount, confidence, window_raw)
                if currency:
                    result.set("currency", currency, confidence, window_raw)

        # Ora. Tiparul cere „ora" inainte sau separatorul `:`, ca sa nu confunde
        # o data („06.09.2026") cu o ora.
        match = patterns.TIME.search(line.normalized)
        if match:
            hour = match.group("h1") or match.group("h2")
            minute = match.group("m1") or match.group("m2")
            # Ora poate fi in afara intervalului daca OCR-ul a citit gresit cifrele.
            with contextlib.suppress(ValueError):
                result.set("time", time(int(hour), int(minute)), line.confidence, line.raw)

        # Adresa si oras.
        match = patterns.ADDRESS.search(line.raw)
        if match:
            result.set("address", match.group(1).strip(" ,."), line.confidence, line.raw)
        match = patterns.POSTAL_CITY.search(line.raw)
        if match:
            result.set("city", match.group(2).strip(), line.confidence, line.raw)

        # Locatie explicita.
        if document_type in {"invitation", "medical"}:
            match = patterns.LOCATION_PREFIX.search(line.raw)
            if match:
                candidate = match.group(1).strip(" ,.")
                if len(candidate) >= 4 and not candidate[0].isdigit():
                    result.set("location", candidate, line.confidence * 0.8, line.raw)

        # Identificatori.
        match = patterns.CUI.search(line.normalized)
        if match:
            result.set("tax_id", match.group(1).upper().replace(" ", ""), line.confidence, line.raw)
        match = patterns.IBAN.search(line.raw.replace(" ", ""))
        if match:
            result.set("iban", match.group(1), line.confidence, line.raw)

        # Companie sau persoana.
        match = patterns.COMPANY.search(line.raw)
        if match:
            result.set("company", match.group(0).strip(), line.confidence * 0.8, line.raw)
        match = patterns.PERSON_LABEL.search(line.raw)
        if match:
            result.set("person", match.group(1).strip(), line.confidence * 0.9, line.raw)

    # Suma fara eticheta: acceptata doar daca are moneda alaturi si randul nu
    # contine un identificator (cod fiscal, IBAN, numar de contract).
    if "amount" not in result.fields:
        for line in lines:
            if patterns.IDENTIFIER_LINE.search(line.normalized.replace(" ", "")):
                continue
            parsed = _parse_amount(line.raw, require_currency=True)
            if parsed:
                amount, currency = parsed
                confidence = max(0.0, line.confidence - NO_LABEL_PENALTY)
                result.set("amount", amount, confidence, line.raw)
                if currency:
                    result.set("currency", currency, confidence, line.raw)
                break

    result.set("suggested_action", suggested_action(result), 0.5)
    return result


def suggested_action(result: Extraction) -> str:
    """Ce propune aplicatia — utilizatorul confirma sau schimba."""
    if "due_date" in result.fields:
        return "reminder"
    if "event_date" in result.fields:
        return "appointment"
    return "note"
