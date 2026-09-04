"""Raspunsul la o intrebare de clarificare completeaza schita, nu o reface.

Pana acum raspunsul era lipit de comanda initiala si totul se interpreta din nou,
de la zero. Orice camp citit corect prima data putea sa dispara la a doua trecere:
utilizatorul raspundea „la trei după-amiaza" si pierdea persoana sau data.

Aici raspunsul este citit strict pentru intrebarea pusa si imbinat peste schita
existenta. Un camp deja completat nu poate deveni gol. Cand raspunsul nu poate fi
folosit pentru intrebarea pusa, schita ramane neatinsa si intrebarea se repeta —
nicio interpretare noua nu are voie sa stearga ce era deja bun.
"""

from __future__ import annotations

from datetime import time
from enum import StrEnum

from apps.assistant import ro_time
from apps.assistant.schemas import Intent, IntentResult
from apps.core.providers.context import IntentContext
from apps.search.normalize import normalize

#: Motivele care intreaba despre zi.
DATE_REASONS = frozenset(
    {
        "data_lipseste",
        "data_ambigua",
        "data_invalida",
        "data_neclara",
        "data_in_conflict",
    }
)

#: Motivele care intreaba despre ora.
TIME_REASONS = frozenset(
    {
        "ora_lipseste",
        "ora_ambigua",
        "ora_neclara",
        "ora_in_conflict",
    }
)

#: Motivele al caror raspuns este un text simplu, si campul in care intra.
TEXT_REASONS = {
    "persoana_nespecificata": "person",
    "titlu_lipseste": "title",
    "continut_lipseste": "title",
    "termen_cautare_lipseste": "search_query",
}

#: Motivele la care intrebarea este „am inteles X, e corect?" — raspunsul poate fi
#: un simplu da sau nu.
CONFIRMATION_REASONS = frozenset({"data_in_conflict", "ora_in_conflict"})

#: Raspunsuri scurte de acceptare, respectiv de respingere. Comparatia se face pe
#: textul normalizat (litere mici, fara diacritice), deci „Da." si „DA" ajung aici.
DA = frozenset({"da", "corect", "e corect", "da e corect", "exact", "asa e", "confirm"})
NU = frozenset({"nu", "nu e corect", "gresit", "e gresit", "nu asa", "nu e asa"})

#: Motivele la care raspunsul asteptat este comanda rostita din nou. Aici nu exista
#: un camp de completat si nici ceva de pastrat: interpretarea veche este cea pusa
#: la indoiala.
REFORMULATION_REASONS = frozenset(
    {
        "incredere_mica",
        "intentie_necunoscuta",
        "intentie_in_conflict",
        "informatie_nesustinuta",
    }
)


class Outcome(StrEnum):
    #: Raspunsul a completat schita existenta.
    MERGED = "merged"
    #: Raspunsul nu se potriveste cu intrebarea; schita ramane, intrebam din nou.
    NOT_UNDERSTOOD = "not_understood"
    #: Raspunsul este comanda reformulata; se interpreteaza de la capat.
    REFORMULATION = "reformulation"


def apply_answer(
    result: IntentResult, answer: str, reason: str, context: IntentContext
) -> tuple[IntentResult, Outcome]:
    """Imbina raspunsul in schita existenta, fara sa piarda nimic din ea."""
    text = answer.strip()
    if not text:
        return result, Outcome.NOT_UNDERSTOOD
    if result.intent == Intent.UNKNOWN or reason in REFORMULATION_REASONS:
        return result, Outcome.REFORMULATION

    data = result.model_dump()
    ambiguity = list(data.get("ambiguity") or [])
    understood = False

    if reason in CONFIRMATION_REASONS:
        confirmat = _yes_no(text)
        if confirmat is True:
            # Valoarea pastrata era cea buna: conflictul se stinge, restul ramane.
            return _finalizeaza(data, [code for code in ambiguity if code != reason])
        if confirmat is False:
            # Nu mai exista nicio valoare in care sa avem incredere. O golim, iar
            # `policy.missing_fields` o cere din nou, cu intrebarea ei obisnuita.
            data["date" if reason == "data_in_conflict" else "start_time"] = None
            data["end_time"] = None
            return _finalizeaza(data, [code for code in ambiguity if code != reason])

    ajustata = _disambiguate_hour(result.start_time, text) if reason == "ora_ambigua" else None
    if ajustata is not None:
        # „După-amiaza." raspunde la „la două", nu inlocuieste ora cu 15:00. Partea
        # de zi alege jumatatea zilei; ora rostita ramane cea rostita.
        data["start_time"] = ajustata
        return _finalizeaza(data, [code for code in ambiguity if code not in TIME_REASONS])

    temporal = ro_time.extract(text, now=context.now)
    # Un camp este completat fie pentru ca despre el s-a intrebat, fie pentru ca
    # lipseste oricum. Nu se suprascrie niciodata o valoare deja buna.
    if temporal.day is not None and (reason in DATE_REASONS or data["date"] is None):
        data["date"] = temporal.day
        ambiguity = [code for code in ambiguity if code not in DATE_REASONS]
        understood = True
    if temporal.at_time is not None and (reason in TIME_REASONS or data["start_time"] is None):
        data["start_time"] = temporal.at_time
        data["all_day"] = False
        ambiguity = [code for code in ambiguity if code not in TIME_REASONS]
        understood = True
    if understood and temporal.ambiguous and temporal.reason:
        # Raspunsul a adus o valoare, dar tot neclara („la 3"): o pastram si
        # intrebam mai departe, in loc sa alegem in locul utilizatorului.
        ambiguity.append(temporal.reason)

    field = TEXT_REASONS.get(reason)
    if not understood and field:
        data[field] = text.strip(" .,;:")[:200]
        ambiguity = [code for code in ambiguity if code != reason]
        understood = True

    if not understood:
        return result, Outcome.NOT_UNDERSTOOD
    return _finalizeaza(data, ambiguity)


def _finalizeaza(data: dict, ambiguity: list[str]) -> tuple[IntentResult, Outcome]:
    data["ambiguity"] = list(dict.fromkeys(ambiguity))
    # Intrebarea providerului a primit un raspuns; altfel ar bloca schita la infinit.
    data["clarification_required"] = False
    data["clarification_question"] = None
    return IntentResult.model_validate(data), Outcome.MERGED


def _yes_no(answer: str) -> bool | None:
    """`True` la acceptare, `False` la respingere, `None` daca raspunsul spune altceva."""
    curatat = normalize(answer).strip(" .,;:!?")
    if curatat in DA:
        return True
    if curatat in NU:
        return False
    return None


def _disambiguate_hour(current: time | None, answer: str) -> time | None:
    """Muta ora curenta in jumatatea de zi indicata de raspuns.

    Se aplica doar cand raspunsul este o parte de zi si nimic altceva: „la două"
    plus „după-amiaza" inseamna 14:00, nu 15:00, cat ar da partea de zi singura.
    """
    if current is None or ro_time.has_explicit_hour(answer):
        return None
    part = ro_time.day_part(answer)
    if part is None:
        return None
    ora = current.hour % 12
    if part >= time(12, 0):
        ora += 12
    return current.replace(hour=ora)
