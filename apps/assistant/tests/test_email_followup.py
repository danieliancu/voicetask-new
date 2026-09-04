"""„Urmărește email": emailul se alege, nu se ghiceste.

Inainte, `drafts.apply` lua „cel mai recent email potrivit" si presupunea „mâine la
09:00" cand lipsea data. Doua mesaje de la aceeasi persoana sunt insa doua lucruri
diferite, iar o greseala se vedea abia dupa salvare.
"""

from __future__ import annotations

import pytest
import time_machine
from django.urls import reverse

from apps.assistant import drafts as drafts_module
from apps.assistant import services
from apps.assistant.forms import EmailFollowUpForm
from apps.assistant.models import IntentDraft
from apps.assistant.schemas import Intent
from apps.assistant.tests._stubs import ACUM, MAINE, ModelSimulat
from apps.core.enums import ItemKind
from apps.core.providers.registry import override_provider
from apps.integrations.models import EmailReference

pytestmark = pytest.mark.django_db

COMANDA = "Urmărește emailul de la Ana."


def model_email(**camp):
    return ModelSimulat(
        intent=Intent.FOLLOW_UP_EMAIL, confidence=0.9, person="Ana", title="Email de la Ana", **camp
    )


def interpreteaza(user, text=COMANDA, **camp) -> IntentDraft:
    with time_machine.travel(ACUM, tick=False), override_provider("intent", model_email(**camp)):
        return services.interpret(user, text)


# ------------------------------------------------------- alegerea emailului


def test_fara_nicio_potrivire_spune_ca_nu_a_gasit(user):
    draft = interpreteaza(user)

    assert draft.payload["target_id"] is None
    assert "email_negasit" in draft.payload["ambiguity"]
    assert draft.status == IntentDraft.Status.NEEDS_CLARIFICATION
    assert "Nu am găsit emailul" in draft.clarification_question


def test_o_singura_potrivire_este_preselectata_dar_afisata(auth_client, user, email_factory):
    email = email_factory(user, subject="Ofertă", sender="Ana Popescu <ana@example.com>")
    draft = interpreteaza(user)

    assert draft.payload["target_id"] == email.pk
    assert draft.target_kind == ItemKind.EMAIL

    with time_machine.travel(ACUM, tick=False):
        html = auth_client.get(reverse("assistant:draft", args=[draft.uid])).content.decode()
    assert "Ana Popescu" in html
    assert "Ofertă" in html


def test_mai_multe_potriviri_lasa_alegerea_utilizatorului(user, email_factory):
    email_factory(user, subject="Ofertă nouă", sender="Ana Popescu <ana@example.com>")
    email_factory(user, subject="Contract", sender="Ana Popescu <ana@example.com>")

    draft = interpreteaza(user)

    assert draft.payload["target_id"] is None
    assert len(draft.candidates) == 2
    assert draft.status == IntentDraft.Status.NEEDS_CLARIFICATION
    assert draft.clarification_question == (
        "Am găsit mai multe emailuri potrivite. Pe care îl alegi?"
    )


def test_emailul_altui_utilizator_nu_este_ales(user, other_user, email_factory):
    strain = email_factory(other_user, subject="Ofertă", sender="Ana Popescu <ana@example.com>")
    draft = interpreteaza(user)

    assert draft.payload["target_id"] != strain.pk
    assert "email_negasit" in draft.payload["ambiguity"]


def test_formularul_respinge_emailul_altui_utilizator(user, other_user, email_factory):
    strain = email_factory(other_user, subject="Ofertă", sender="Ana <ana@example.com>")
    email_factory(user, subject="Al meu", sender="Ion <ion@example.com>")
    draft = interpreteaza(user)

    form = EmailFollowUpForm(
        {"target_id": str(strain.pk), "date": MAINE, "start_time": "09:00"}, draft=draft
    )

    assert not form.is_valid()
    assert "target_id" in form.errors


# --------------------------------------------------- data si ora nu se presupun


def test_lipsa_datei_este_ceruta_nu_presupusa(user, email_factory):
    """Inainte, o urmarire fara data se aseza tacit peste o zi."""
    email_factory(user, subject="Ofertă", sender="Ana Popescu <ana@example.com>")
    draft = interpreteaza(user)

    assert draft.payload["date"] is None
    assert draft.clarification_question == "În ce zi să îți amintesc de email?"


def test_lipsa_orei_este_ceruta_nu_presupusa(user, email_factory):
    """Inainte, ora lipsa devenea 09:00 prin `FOLLOW_UP_TIME`."""
    email_factory(user, subject="Ofertă", sender="Ana Popescu <ana@example.com>")
    # Ziua trebuie rostita: altfel reconcilierea o scoate ca nesustinuta de text.
    draft = interpreteaza(user, "Urmărește mâine emailul de la Ana.", date=MAINE)

    assert draft.payload["start_time"] is None
    assert draft.clarification_question == "La ce oră să îți amintesc?"


@pytest.mark.parametrize("lipsa", ["date", "start_time"])
def test_aplicarea_refuza_urmarirea_incompleta(user, email_factory, lipsa):
    email = email_factory(user, subject="Ofertă", sender="Ana <ana@example.com>")
    payload = {
        "intent": Intent.FOLLOW_UP_EMAIL,
        "target_id": email.pk,
        "target_kind": ItemKind.EMAIL,
        "date": MAINE,
        "start_time": "09:00:00",
        "confidence": 0.9,
    }
    payload[lipsa] = None
    draft = IntentDraft.objects.create(
        owner=user, intent=Intent.FOLLOW_UP_EMAIL, payload=payload, target_id=email.pk
    )

    with pytest.raises(drafts_module.DraftError):
        drafts_module.apply(draft)

    email.refresh_from_db()
    assert email.status == EmailReference.Status.NEW


def test_nu_mai_exista_valori_implicite_in_cod():
    """`FOLLOW_UP_TIME` si „peste o zi" au disparut din calea de salvare."""
    sursa = (drafts_module.__file__).replace(".pyc", ".py")
    with open(sursa, encoding="utf-8") as handle:
        text = handle.read()

    assert "FOLLOW_UP_TIME" not in text
    assert "timedelta(days=1)" not in text


# ------------------------------------------------------------------ salvarea


def test_urmarirea_completa_salveaza_emailul_ales_si_nota(user, email_factory):
    email_factory(user, subject="Altceva", sender="Ion <ion@example.com>")
    ales = email_factory(user, subject="Ofertă", sender="Ana Popescu <ana@example.com>")
    draft = interpreteaza(user, date=MAINE, start_time="09:00")

    form = EmailFollowUpForm(
        {
            "target_id": str(ales.pk),
            "date": MAINE,
            "start_time": "15:30",
            "description": "de răspuns până vineri",
        },
        draft=draft,
    )
    assert form.is_valid(), form.errors

    with time_machine.travel(ACUM, tick=False):
        kind, pk = drafts_module.apply(draft, overrides=form.to_overrides())

    ales.refresh_from_db()
    assert (kind, pk) == (ItemKind.EMAIL, ales.pk)
    assert ales.status == EmailReference.Status.FOLLOW_UP
    assert ales.follow_up_note == "de răspuns până vineri"
    assert ales.follow_up_at is not None


def test_expeditorul_si_subiectul_nu_sunt_campuri_de_completat(user, email_factory):
    email_factory(user, subject="Ofertă", sender="Ana Popescu <ana@example.com>")
    form = EmailFollowUpForm(draft=interpreteaza(user))

    assert "sender" not in form.fields
    assert "subject" not in form.fields
    assert form.selected_email is not None
