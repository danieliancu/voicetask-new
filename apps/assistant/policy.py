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
    "ora_lipseste": "La ce oră este întâlnirea?",
    "titlu_lipseste": "Despre ce este vorba?",
    "continut_lipseste": "Ce să notez?",
    "termen_cautare_lipseste": "Ce anume să caut?",
    "data_ambigua": "Data nu este clară. Pentru ce zi anume?",
    "data_invalida": "Data nu pare validă. Poți să o spui altfel?",
    "data_neclara": "Nu am înțeles data. Pentru ce zi anume?",
    "data_in_conflict": "Nu sunt sigur de dată. Spune încă o dată ziua.",
    "ora_ambigua": "Ora nu este clară. Dimineața sau după-amiaza?",
    "ora_neclara": "Nu am înțeles ora. La ce oră anume?",
    "ora_in_conflict": "Nu sunt sigur de oră. Spune încă o dată ora.",
    "informatie_nesustinuta": "Nu am reținut bine detaliile. Poți să le repeți?",
    "intentie_in_conflict": "Nu sunt sigur ce vrei să fac. Poți reformula?",
    "persoana_nespecificata": "Despre ce persoană este vorba?",
    "tinta_nespecificata": "La ce element te referi?",
    "candidati_multipli": "Am găsit mai multe elemente potrivite. Pe care îl alegi?",
    "incredere_mica": "Nu sunt sigur ce ai cerut. Poți reformula?",
    "confirmare_stergere": "Confirmi ștergerea?",
}

#: Cateva intrebari suna altfel in functie de ce se creeaza. „La ce oră este
#: întâlnirea?" nu are sens pentru o alarma de luat medicamentul.
QUESTIONS_BY_INTENT = {
    (Intent.CREATE_REMINDER, "data_lipseste"): "Pentru ce dată să setez alarma?",
    (Intent.CREATE_REMINDER, "ora_lipseste"): "La ce oră să te anunț?",
    (Intent.CREATE_REMINDER, "titlu_lipseste"): "Pentru ce să te anunț?",
}

#: Ce trebuie sa contina o schita ca sa poata fi salvata. Lipsa oricaruia dintre
#: aceste campuri este o intrebare, niciodata o valoare implicita.
REQUIRED_FIELDS: dict[Intent, tuple[tuple[str, str], ...]] = {
    Intent.CREATE_APPOINTMENT: (
        ("title", "titlu_lipseste"),
        ("date", "data_lipseste"),
        ("start_time", "ora_lipseste"),
    ),
    Intent.CREATE_REMINDER: (
        ("title", "titlu_lipseste"),
        ("date", "data_lipseste"),
        ("start_time", "ora_lipseste"),
    ),
    Intent.SEARCH: (("search_query", "termen_cautare_lipseste"),),
    Intent.FOLLOW_UP_EMAIL: (("person", "persoana_nespecificata"),),
}


def question_for(result: IntentResult, reason: str) -> str:
    return QUESTIONS_BY_INTENT.get((result.intent, reason)) or QUESTIONS.get(
        reason, QUESTIONS["incredere_mica"]
    )


def missing_fields(result: IntentResult) -> list[str]:
    """Motivele pentru care schita nu este completa, in ordinea in care se cer.

    O programare „toată ziua" este singura care poate ramane fara ora, si numai
    pentru ca utilizatorul a cerut-o explicit.
    """
    if result.intent == Intent.CREATE_NOTE:
        return [] if (result.title or result.description) else ["continut_lipseste"]

    missing = []
    for field, reason in REQUIRED_FIELDS.get(result.intent, ()):
        if field == "start_time" and result.all_day:
            continue
        if getattr(result, field) in (None, ""):
            missing.append(reason)
    return missing


#: Motive pe care parserul le noteaza in `ambiguity` la interpretare, dar care pot
#: fi rezolvate ulterior — tinta unei modificari este cautata dupa interpretare, in
#: `services.interpret`. Deciziile de mai sus le trateaza pe starea reala a schitei,
#: asa ca nota veche nu mai are ce cauta in bucla.
RESOLVED_ELSEWHERE = frozenset({"tinta_nespecificata"})


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


def decide(
    result: IntentResult, *, candidate_count: int = 0, degraded: bool = False
) -> Decision:
    """Decide daca schita poate fi confirmata sau trebuie lamurita.

    `degraded=True` marcheaza un rezultat produs de rezerva locala, dupa ce
    serviciul extern a esuat. Increderea raportata de parserul pe reguli este
    a lui, nu a interpretarii cerute, asa ca pragul de lamurire creste: preferam
    o intrebare in plus in locul unei schite gresite.
    """
    threshold = (
        settings.INTENT_CONFIDENCE_AUTOFILL if degraded else settings.INTENT_CONFIDENCE_CLARIFY
    )

    if result.intent == Intent.UNKNOWN:
        return Decision(
            can_confirm=False,
            needs_clarification=True,
            question=QUESTIONS["incredere_mica"],
            reason="intentie_necunoscuta",
        )

    if result.confidence < threshold:
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

    # Orice motiv cunoscut opreste confirmarea. Filtrarea printr-o lista scurta ar
    # face ca un motiv nou — de pilda un conflict intre model si parser — sa fie
    # inregistrat in schita si ignorat tacit la decizie.
    for reason in result.ambiguity:
        if reason in QUESTIONS and reason not in RESOLVED_ELSEWHERE:
            return Decision(
                can_confirm=False,
                needs_clarification=True,
                question=question_for(result, reason),
                reason=reason,
                requires_explicit_confirmation=result.is_destructive,
            )

    for reason in missing_fields(result):
        return Decision(
            can_confirm=False,
            needs_clarification=True,
            question=question_for(result, reason),
            reason=reason,
        )

    # Totul este clar. Utilizatorul vede oricum schita si apasa „Salvează".
    return Decision(
        can_confirm=True,
        needs_clarification=False,
        requires_explicit_confirmation=result.is_destructive,
    )
