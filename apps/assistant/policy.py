"""Cand executam o comanda si cand cerem clarificare.

Regula de baza: nimic nu se salveaza si nimic nu se sterge fara o confirmare
vizibila. Schita este intotdeauna afisata; clarificarea este ceruta suplimentar
cand interpretarea este nesigura.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

from apps.assistant.schemas import Intent, IntentResult

QUESTIONS = {
    "data_lipseste": "Pentru ce dată să o programez?",
    "data_ambigua": "Data nu este clară. Pentru ce zi anume?",
    "data_invalida": "Data nu pare validă. Poți să o spui altfel?",
    "ora_ambigua": "Ora nu este clară. Dimineața sau după-amiaza?",
    "persoana_nespecificata": "Despre ce persoană este vorba?",
    "tinta_nespecificata": "La ce element te referi?",
    "candidati_multipli": "Am găsit mai multe elemente potrivite. Pe care îl alegi?",
    "incredere_mica": "Nu sunt sigur ce ai cerut. Poți reformula?",
    "confirmare_stergere": "Confirmi ștergerea?",
}


@dataclass(frozen=True)
class Decision:
    #: Schita poate fi salvata direct de utilizator (dupa ce o vede si o confirma).
    can_confirm: bool
    #: Trebuie raspuns la o intrebare inainte de a putea confirma.
    needs_clarification: bool
    question: str = ""
    reason: str = ""
    #: Actiunile distructive cer un al doilea pas explicit, chiar cand totul e clar.
    requires_explicit_confirmation: bool = False


def decide(result: IntentResult, *, candidate_count: int = 0) -> Decision:
    if result.intent == Intent.UNKNOWN:
        return Decision(
            can_confirm=False,
            needs_clarification=True,
            question=QUESTIONS["incredere_mica"],
            reason="intentie_necunoscuta",
        )

    if result.confidence < settings.INTENT_CONFIDENCE_CLARIFY:
        return Decision(
            can_confirm=False,
            needs_clarification=True,
            question=result.clarification_question or QUESTIONS["incredere_mica"],
            reason="incredere_mica",
        )

    if result.clarification_required:
        return Decision(
            can_confirm=False,
            needs_clarification=True,
            question=result.clarification_question or QUESTIONS["incredere_mica"],
            reason="cerut_de_provider",
            requires_explicit_confirmation=result.is_destructive,
        )

    if result.needs_target:
        if candidate_count > 1 and result.target_id is None:
            return Decision(
                can_confirm=False,
                needs_clarification=True,
                question=QUESTIONS["candidati_multipli"],
                reason="candidati_multipli",
                requires_explicit_confirmation=result.is_destructive,
            )
        if result.target_id is None:
            return Decision(
                can_confirm=False,
                needs_clarification=True,
                question=QUESTIONS["tinta_nespecificata"],
                reason="tinta_nespecificata",
                requires_explicit_confirmation=result.is_destructive,
            )

    for reason in result.ambiguity:
        if reason in {"data_ambigua", "data_invalida", "ora_ambigua", "persoana_nespecificata"}:
            return Decision(
                can_confirm=False,
                needs_clarification=True,
                question=QUESTIONS[reason],
                reason=reason,
                requires_explicit_confirmation=result.is_destructive,
            )

    if result.intent in {Intent.CREATE_APPOINTMENT, Intent.CREATE_REMINDER} and result.date is None:
        return Decision(
            can_confirm=False,
            needs_clarification=True,
            question=QUESTIONS["data_lipseste"],
            reason="data_lipseste",
        )

    # Totul este clar. Utilizatorul vede oricum schita si apasa „Salvează".
    return Decision(
        can_confirm=True,
        needs_clarification=False,
        requires_explicit_confirmation=result.is_destructive,
    )
