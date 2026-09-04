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
        "zi_saptamana_lipseste",
        "interval_sau_data",
    }
)

#: Motivele care intreaba despre ora de inceput.
TIME_REASONS = frozenset(
    {
        "ora_lipseste",
        "ora_ambigua",
        "ora_neclara",
        "ora_in_conflict",
        "interval_sau_data",
    }
)

#: Motivele care intreaba despre ora de final a unui interval.
END_TIME_REASONS = frozenset({"ora_final_neclara", "ora_final_in_conflict", "interval_invalid"})

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
        "editare_ambigua",
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

    # „La ce oră după-amiaza?" — partea de zi este retinuta in codul motivului, deci
    # raspunsul „la trei" se aseaza inapoi in aceeasi jumatate a zilei.
    part = ro_time.part_from_reason(reason)
    if part is not None:
        placed = _hour_in_part(text, part, context)
        if placed is None:
            return result, Outcome.NOT_UNDERSTOOD
        data["start_time"] = placed
        data["all_day"] = False
        return _finalizeaza(data, _fara_motive_de_ora(ambiguity))

    ajustata = _disambiguate_hour(result.start_time, text) if reason == "ora_ambigua" else None
    if ajustata is not None:
        # „După-amiaza." raspunde la „la două", nu inlocuieste ora cu 15:00. Partea
        # de zi alege jumatatea zilei; ora rostita ramane cea rostita.
        data["start_time"] = ajustata
        return _finalizeaza(data, _fara_motive_de_ora(ambiguity))

    temporal = ro_time.extract(text, now=context.now)

    if reason == "zi_saptamana_lipseste":
        weekday = ro_time.weekday_from_text(text)
        if weekday is not None:
            data["date"] = ro_time.weekday_next_week(context.now.date(), weekday)
            ambiguity = [code for code in ambiguity if code not in DATE_REASONS]
            understood = True

    if reason in END_TIME_REASONS:
        start = data["start_time"]
        if temporal.at_time is not None and start is not None and temporal.at_time > start:
            data["end_time"] = temporal.at_time
            ambiguity = [code for code in ambiguity if code not in END_TIME_REASONS]
            understood = True
        return (
            _finalizeaza(data, ambiguity) if understood else (result, Outcome.NOT_UNDERSTOOD)
        )

    # Un camp este completat fie pentru ca despre el s-a intrebat, fie pentru ca
    # lipseste oricum. Nu se suprascrie niciodata o valoare deja buna.
    if not understood and temporal.day is not None and (reason in DATE_REASONS or not data["date"]):
        data["date"] = temporal.day
        ambiguity = [code for code in ambiguity if code not in DATE_REASONS]
        understood = True
    if temporal.at_time is not None and (reason in TIME_REASONS or data["start_time"] is None):
        data["start_time"] = temporal.at_time
        data["all_day"] = False
        ambiguity = _fara_motive_de_ora(ambiguity)
        understood = True
        if temporal.end_time is not None:
            data["end_time"] = temporal.end_time
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


def _fara_motive_de_ora(ambiguity: list[str]) -> list[str]:
    """Scoate si motivele fixe, si pe cele care poarta cu ele o parte de zi."""
    return [
        code
        for code in ambiguity
        if code not in TIME_REASONS and not code.startswith(ro_time.VAGUE_HOUR_PREFIX)
    ]


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


def _hour_in_part(text: str, part: ro_time.DayPart, context: IntentContext) -> time | None:
    """Ora din raspuns, asezata in partea de zi rostita in comanda initiala."""
    spoken = ro_time.extract(text, now=context.now)
    if spoken.at_time is None:
        return None
    if ro_time.has_ampm(text):
        # AM/PM rostit explicit bate partea retinuta: utilizatorul s-a razgandit.
        return spoken.at_time
    hour = spoken.at_time.hour % 12 or 12
    return spoken.at_time.replace(hour=part.place(hour) % 24)


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
    if part.exact is not None:
        return part.exact
    return current.replace(hour=part.place(current.hour % 12 or 12) % 24)
