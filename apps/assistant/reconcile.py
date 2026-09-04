"""Reconcilierea rezultatului modelului AI cu parserul determinist.

Modelul citeste intentia bine, dar aritmetica pe date („mâine" fata de momentul
comenzii) o face inconstant si uneori raspunde `date: null` pentru o fraza care
contine o data limpede. Pana acum nimeni nu verifica: raspunsul trecea doar prin
validarea de tip si ajungea direct in schita.

Aici se intalnesc cele doua interpretari. Pentru timp, sursa principala este
`ro_time`: ce recunoaste el sigur completeaza sau corecteaza modelul. Pentru
persoane, locatii si sume, fiecare valoare venita de la model trebuie sa se
regaseasca in transcriere — altfel este scoasa, nu „reparata".

Stratul nu inventeaza niciodata o valoare si nu creste niciodata increderea. Tot
ce nu se poate decide determinist devine un motiv in `ambiguity`, iar `policy`
transforma motivul intr-o intrebare si blocheaza confirmarea.
"""

from __future__ import annotations

import re
from typing import Any

from apps.assistant import ro_time
from apps.assistant.providers.rule_based import (
    INTENT_PATTERNS,
    VERB_SCORE,
    RuleBasedIntentParser,
    detect_intent,
)
from apps.assistant.schemas import MUTATING_INTENTS, Intent, IntentResult
from apps.core.providers.context import IntentContext
from apps.search.normalize import fold, normalize

#: Parserul determinist, folosit ca a doua opinie. Nu are stare, deci o instanta
#: de modul ajunge; `parse` primeste oricum tot contextul ca argument.
_RULES = RuleBasedIntentParser()

#: Verbele de notare. Daca sunt rostite, intentia modelului nu se mai corecteaza:
#: „Notează că mă întâlnesc mâine cu Ion" este o notita, nu o programare.
_NOTE_PATTERNS = dict(INTENT_PATTERNS)[Intent.CREATE_NOTE]

#: Intentiile spre care o notita — raspunsul implicit al modelului cand nu
#: recunoaste un verb — poate fi ridicata de o potrivire deterministica.
_PROMOTABLE = frozenset({Intent.CREATE_APPOINTMENT, Intent.CREATE_REMINDER})

_TOKEN = re.compile(r"[0-9a-z]+")


def _choose(
    py_value: Any,
    ai_value: Any,
    *,
    marker: bool,
    conflict: str,
    unclear: str,
) -> tuple[Any, str | None]:
    """Alege intre valoarea deterministica si cea a modelului.

    Ordinea regulilor este si ordinea increderii: ce a citit Python din text bate
    ce a dedus modelul; ce modelul a produs fara sprijin in text nu supravietuieste.
    """
    if py_value is not None:
        if ai_value is None or ai_value == py_value:
            return py_value, None
        # Amandoua au o valoare, dar diferita. Pastram citirea deterministica si
        # cerem confirmarea; nu alegem tacit una dintre ele.
        return py_value, conflict
    if ai_value is None:
        return None, None
    if marker:
        # S-a rostit ceva temporal pe care `ro_time` nu stie sa il citeasca.
        # Valoarea modelului ramane, dar nu se poate confirma fara intrebare.
        return ai_value, unclear
    # Nimic in transcriere nu justifica valoarea: modelul a inventat-o. Se scoate
    # fara alt semnal — lipsa ei este deja tratata de `policy.missing_fields`, care
    # pune intrebarea fireasca („La ce oră este întâlnirea?") in locul unei plangeri.
    return None, None


def _is_grounded(value: str, haystack: str) -> bool:
    """Fiecare cuvant al valorii apare in transcrierea normalizata?

    `normalize` scoate diacriticele si trece la litere mici de ambele parti, deci
    „Ion" se regaseste in „ION" si „Ana" in „Ána". Tokenurile de o litera sunt
    ignorate: numerele de la adrese si initialele nu spun nimic despre sustinere.
    """
    tokens = [token for token in _TOKEN.findall(normalize(value)) if len(token) > 1]
    return bool(tokens) and all(token in haystack for token in tokens)


def _reconcile_intent(
    ai_intent: Intent, folded: str, context: IntentContext
) -> tuple[Intent, str | None]:
    py_intent, score = detect_intent(folded, context)
    if score < VERB_SCORE or py_intent == ai_intent:
        return ai_intent, None

    if (
        ai_intent == Intent.CREATE_NOTE
        and py_intent in _PROMOTABLE
        and not any(re.search(pattern, folded) for pattern in _NOTE_PATTERNS)
    ):
        # „Mă întâlnesc mâine cu Ion" nu contine niciun verb de comanda, asa ca
        # modelul cade pe notita. Verbul rostit spune altceva, fara echivoc.
        return py_intent, None

    if (
        (ai_intent in MUTATING_INTENTS) != (py_intent in MUTATING_INTENTS)
        # Pe ecranul „Modifică" tinta este deja aleasa, deci o intentie de
        # modificare nu contrazice nimic: acolo se ajunge tocmai ca sa modifici.
        and not (context.mode == "edit" and ai_intent in MUTATING_INTENTS)
    ):
        # Una dintre interpretari modifica sau sterge un obiect existent, cealalta
        # creeaza unul nou. Diferenta e prea mare ca sa fie rezolvata tacit.
        return ai_intent, "intentie_in_conflict"

    return ai_intent, None


def reconcile(result: IntentResult, text: str, context: IntentContext) -> IntentResult:
    """Confrunta rezultatul modelului cu parserul determinist si completeaza schita."""
    if result.intent == Intent.UNKNOWN or not text.strip():
        return result

    folded = fold(text)
    haystack = normalize(text)
    temporal = ro_time.extract(text, now=context.now)
    reference = _RULES.parse(text, context=context)

    reasons: list[str] = []
    data = result.model_dump()

    intent, intent_reason = _reconcile_intent(result.intent, folded, context)
    data["intent"] = intent
    if intent_reason:
        reasons.append(intent_reason)

    # --- data si ora: parserul determinist este sursa principala ---------------
    data["date"], reason = _choose(
        temporal.day,
        result.date,
        marker=ro_time.has_date_marker(text),
        conflict="data_in_conflict",
        unclear="data_neclara",
    )
    if reason:
        reasons.append(reason)

    if data.get("all_day") and temporal.at_time is not None:
        # S-a rostit o ora: „toată ziua" a fost presupunerea modelului, nu a
        # utilizatorului.
        data["all_day"] = False

    if not data.get("all_day"):
        data["start_time"], reason = _choose(
            temporal.at_time,
            result.start_time,
            marker=ro_time.has_time_marker(text),
            conflict="ora_in_conflict",
            unclear="ora_neclara",
        )
        if reason:
            reasons.append(reason)

        data["end_time"], reason = _choose(
            temporal.end_time,
            result.end_time,
            # O ora de final se sustine doar pe o formulare de interval, nu pe orice
            # ora din text: „mâine la 10" nu spune nimic despre cand se termina.
            marker=ro_time.has_range_marker(text),
            conflict="ora_final_in_conflict",
            unclear="ora_final_neclara",
        )
        if reason:
            reasons.append(reason)

        start, end = data["start_time"], data["end_time"]
        # O ora de final fara inceput nu inseamna nimic. Una dinaintea inceputului
        # ar face schema sa refuze schita intreaga, deci intrebam in loc sa ghicim
        # ca intervalul trece in ziua urmatoare.
        if end is not None and (start is None or end <= start):
            if start is not None:
                reasons.append("interval_invalid")
            data["end_time"] = None

    reasons.extend(temporal.reasons)

    # --- campuri concrete: se completeaza din text, nu se inventeaza -----------
    for field in ("person", "location"):
        value = data.get(field)
        if value and not _is_grounded(value, haystack):
            data[field] = None
            reasons.append("informatie_nesustinuta")
        if data.get(field) is None and reference.get(field):
            data[field] = reference[field]

    if data.get("amount") is not None and not _is_grounded(
        f"{data['amount']:g}", haystack.replace(",", ".")
    ):
        data["amount"] = None
        data["currency"] = None
        reasons.append("informatie_nesustinuta")

    # --- etichete: se completeaza doar cand modelul nu a dat nimic -------------
    person = data.get("person")
    if intent != Intent.SEARCH and (
        not data.get("title")
        # Un titlu care este doar numele persoanei nu spune nimic in plus fata de
        # campul „persoană"; in lista de programari ar aparea un nume singur.
        or (person and normalize(data["title"]) == normalize(person))
    ):
        data["title"] = _fallback_title(intent, person, reference)
    if intent == Intent.SEARCH and not data.get("search_query"):
        data["search_query"] = reference.get("search_query")
    if intent == Intent.CREATE_APPOINTMENT and data.get("reminder_offset") is None:
        data["reminder_offset"] = context.default_reminder_offset

    # Acelasi motiv poate veni si de la parser, si de aici. O singura data e destul:
    # politica raspunde oricum cu o singura intrebare.
    data["ambiguity"] = list(dict.fromkeys([*data.get("ambiguity", []), *reasons]))
    # Reconstruit prin schema, nu prin `model_copy`: orice incoerenta introdusa
    # aici trebuie sa se vada acum, nu la salvare.
    return IntentResult.model_validate(data)


def _fallback_title(intent: Intent, person: str | None, reference: dict) -> str | None:
    if intent == Intent.CREATE_APPOINTMENT and person:
        return f"Întâlnire cu {person}"
    return reference.get("title") or None
