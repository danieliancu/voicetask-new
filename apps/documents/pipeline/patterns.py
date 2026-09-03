r"""Tipare pentru extragerea datelor din documente romanesti.

Toate expresiile ruleaza pe textul normalizat (fara diacritice, litere mici),
fiindca OCR-ul greseste frecvent ș/ț/ă/î. Textul original se pastreaza separat
pentru valorile afisate.

Etichetele folosesc `\s*` in loc de `\s+` intre cuvinte: modelele de recunoastere
antrenate pe alte limbi returneaza frecvent randuri lipite („DATALIMITADEPLATA").
Cu `\s*` acelasi tipar prinde ambele forme.
"""

from __future__ import annotations

import re

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
    "ian": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "iun": 6,
    "iul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "noi": 11,
    "dec": 12,
}

# --- date ------------------------------------------------------------------

# `(?<!\d)` in loc de `\b`: pe randurile lipite data poate urma direct dupa o
# litera („Dataemiteri01.09.2026"), unde `\b` nu se potriveste.
DATE_NUMERIC = re.compile(r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})(?!\d)")
DATE_TEXT = re.compile(
    r"(?<!\d)(\d{1,2})\s*(" + "|".join(MONTHS) + r")\.?\s*(\d{4})?(?![\w.])"
)

#: Etichetele care preced data limita de plata.
DUE_DATE_LABELS = (
    r"data\s*limita\s*de\s*plata",
    r"data\s*limita",
    r"termen\s*de\s*plata",
    r"scadenta",
    r"data\s*scadentei",
    r"plata\s*pana\s*la",
    r"de\s*plata\s*pana\s*la",
)

DOCUMENT_DATE_LABELS = (
    r"data\s*emiteri",
    r"data\s*facturii",
    r"emisa\s*la",
    r"data\s*documentului",
)

EVENT_DATE_LABELS = (
    r"data\s*evenimentului",
    r"va\s*asteptam",
    r"va\s*invitam",
    r"are\s*loc",
)

# --- sume ------------------------------------------------------------------

CURRENCY_ALTERNATIVES = r"lei|ron|eur|euro|usd|gbp|£|\$|€"

AMOUNT = re.compile(
    r"(?P<before>(?:" + CURRENCY_ALTERNATIVES + r")\s*)?"
    r"(?P<number>\d{1,3}(?:[ .]\d{3})*[,.]\d{2}|\d+[,.]\d{2}|\d+)"
    r"(?P<after>\s*(?:" + CURRENCY_ALTERNATIVES + r"))?",
    re.IGNORECASE,
)

#: Fara eticheta („TOTAL DE PLATĂ"), o suma este acceptata doar daca are moneda
#: alaturi. Altfel un cod fiscal sau un numar de contract ar trece drept suma.
AMOUNT_WITH_CURRENCY = re.compile(
    r"(?:(?:" + CURRENCY_ALTERNATIVES + r")\s*"
    r"(?P<number1>\d{1,3}(?:[ .]\d{3})*[,.]\d{2}|\d+(?:[,.]\d{2})?)"
    r"|(?P<number2>\d{1,3}(?:[ .]\d{3})*[,.]\d{2}|\d+(?:[,.]\d{2})?)"
    r"\s*(?:" + CURRENCY_ALTERNATIVES + r"))",
    re.IGNORECASE,
)

TOTAL_LABELS = (
    r"total\s*de\s*plata",
    r"total\s*de\s*achitat",
    r"total\s*factura",
    r"suma\s*de\s*plata",
    r"total\s*general",
    r"\btotal\b",
)

CURRENCY_MAP = {
    "lei": "lei",
    "ron": "lei",
    "eur": "EUR",
    "euro": "EUR",
    "€": "EUR",
    "usd": "USD",
    "$": "USD",
    "gbp": "GBP",
    "£": "GBP",
}

# --- ora si loc -------------------------------------------------------------

#: Ora trebuie sa aiba fie „ora" inainte, fie separatorul `:`. Altfel „06.09.2026"
#: ar fi citita ca 06:09. Lookahead-ul exclude al treilea grup al unei date.
TIME = re.compile(
    r"(?:ora\s*(?P<h1>[01]?\d|2[0-3])[:.](?P<m1>[0-5]\d)"
    r"|(?<![\d:.])(?P<h2>[01]?\d|2[0-3]):(?P<m2>[0-5]\d))(?![.\-/]?\d)"
)

LOCATION_PREFIX = re.compile(
    r"\b(?:la|in|adresa|locatie|locatia|sala|sediul)\s*:?\s*([\w .,-]{4,60})",
)

ADDRESS = re.compile(
    r"\b((?:str\.?|strada|bd\.?|bulevardul|calea|aleea|sos\.?|soseaua)\s*[\w .,-]{3,60})",
    re.IGNORECASE,
)

POSTAL_CITY = re.compile(r"(?<!\d)(\d{6})\s*([A-Za-zĂÂÎȘȚăâîșț-]+(?:[- ][A-Za-zĂÂÎȘȚăâîșț]+)*)")

# --- identificatori ---------------------------------------------------------

CUI = re.compile(r"\b(?:cui|cif)\s*:?\s*(ro\s?\d{2,10})\b")
IBAN = re.compile(r"\b(RO\d{2}[A-Z0-9]{16})\b")
INVOICE_SERIES = re.compile(r"\b(?:seria|serie)\s*([a-z]{1,4})\s*(?:nr\.?\s*)?(\d{3,12})\b")

#: Un rand care contine un identificator nu contine si suma de plata.
IDENTIFIER_LINE = re.compile(r"(?:cui|cif|seria|iban|cont|telefon|contract|codloc)")

# --- tipul documentului -----------------------------------------------------

TYPE_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("invoice", ("factura", "totaldeplata", "furnizor", "cui", "tva")),
    ("invitation", ("invitatie", "vainvitam", "vaasteptam", "serbare", "petrecere")),
    ("medical", ("clinica", "medic", "consultatie", "reteta", "analize", "spital")),
    ("receipt", ("bonfiscal", "chitanta", "casademarcat", "bondecasa")),
    ("letter", ("stimate", "stimata", "cudeosebitaconsideratie", "notificare")),
)

# --- persoane si companii ---------------------------------------------------

COMPANY = re.compile(
    r"\b([A-ZĂÂÎȘȚ][\w&.-]*(?:\s+[A-ZĂÂÎȘȚ][\w&.-]*)*)\s+(?:s\.?r\.?l|s\.?a)\b",
    re.IGNORECASE,
)
PERSON_LABEL = re.compile(
    r"\b(?:client|beneficiar|destinatar|catre|nume)\s*:?\s*"
    r"([A-ZĂÂÎȘȚ][\wăâîșț-]+(?:\s+[A-ZĂÂÎȘȚ][\wăâîșț-]+){0,2})"
)
