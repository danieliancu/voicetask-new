"""Comenzile neclare cer clarificare; cele distructive cer confirmare."""

import pytest
from django.utils import timezone

from apps.assistant import policy, services
from apps.assistant.models import IntentDraft
from apps.assistant.providers.rule_based import RuleBasedIntentParser
from apps.assistant.schemas import Intent, IntentResult
from apps.core.providers.context import IntentContext

pytestmark = pytest.mark.django_db


def ctx(**kwargs):
    return IntentContext(now=timezone.localtime(), **kwargs)


def parse(text: str, **kwargs) -> IntentResult:
    from apps.assistant.schemas import parse_result

    return parse_result(RuleBasedIntentParser().parse(text, context=ctx(**kwargs)))


def test_incredere_mica_cere_clarificare():
    result = IntentResult(intent=Intent.CREATE_NOTE, title="X", confidence=0.2)
    decision = policy.decide(result)
    assert decision.needs_clarification
    assert not decision.can_confirm


def test_intentia_necunoscuta_cere_clarificare():
    decision = policy.decide(IntentResult(intent=Intent.UNKNOWN))
    assert decision.needs_clarification


def test_alarma_fara_data_cere_clarificare():
    result = parse("Pune-mi o alarmă")
    decision = policy.decide(result)
    assert "data_lipseste" in result.ambiguity
    assert decision.needs_clarification
    assert "dată" in decision.question.lower()


def test_ora_ambigua_cere_clarificare():
    result = parse("Programează o întâlnire mâine la 3")
    decision = policy.decide(result)
    assert "ora_ambigua" in result.ambiguity
    assert decision.needs_clarification


def test_stergerea_cere_confirmare_explicita_chiar_daca_este_clara():
    result = IntentResult(
        intent=Intent.DELETE_ITEM, target_id=5, target_kind="notita", confidence=0.95
    )
    decision = policy.decide(result)
    assert decision.can_confirm
    assert decision.requires_explicit_confirmation


def test_candidatii_multipli_cer_alegere():
    result = IntentResult(intent=Intent.DELETE_ITEM, confidence=0.9)
    decision = policy.decide(result, candidate_count=3)
    assert decision.needs_clarification
    assert not decision.can_confirm


def test_urmarirea_cere_emailul_nu_persoana():
    """Doua mesaje de la aceeasi persoana sunt doua lucruri diferite.

    Numele expeditorului nu identifica emailul, deci nu el este intrebat: schita
    are nevoie de mesajul ales, cerut de `policy.missing_fields`.
    """
    result = parse("Urmărește emailul")
    if result.intent is Intent.FOLLOW_UP_EMAIL:
        assert "persoana_nespecificata" not in result.ambiguity
        assert policy.missing_fields(result)[0] == "email_nespecificat"


def test_schita_ambigua_este_marcata_in_baza_de_date(user):
    draft = services.interpret(user, "Pune-mi o alarmă")
    assert draft.status == IntentDraft.Status.NEEDS_CLARIFICATION
    assert draft.clarification_question


def test_schita_clara_ramane_editabila(user):
    draft = services.interpret(user, "Notează că trebuie să sun la bancă")
    assert draft.status == IntentDraft.Status.DRAFT
    assert draft.intent == Intent.CREATE_NOTE


def test_stergerea_fara_tinta_nu_se_poate_aplica(user, note_factory):
    """Fara un obiect identificat, comanda de stergere nu se executa."""
    from apps.assistant import drafts

    draft = services.interpret(user, "Șterge ceva")
    with pytest.raises(drafts.DraftError):
        drafts.apply(draft)


def test_stergerea_cu_tinta_unica_gaseste_obiectul(user, note_factory):
    note_factory(user, title="Lista cumpărături")
    draft = services.interpret(user, "Șterge notița Lista cumpărături")
    assert draft.target_id is not None
    assert draft.target_kind == "notita"


def test_candidatii_apropiati_nu_sunt_alesi_automat(user, note_factory):
    note_factory(user, title="Ședință proiect Alpha")
    note_factory(user, title="Ședință proiect Beta")

    draft = services.interpret(user, "Șterge notița Ședință proiect")

    assert draft.target_id is None
    assert len(draft.candidates) >= 2
    assert draft.status == IntentDraft.Status.NEEDS_CLARIFICATION
