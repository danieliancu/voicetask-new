"""Fluxul schita -> confirmare -> obiect salvat."""

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.assistant import drafts, services
from apps.assistant.models import IntentDraft
from apps.notes.models import Note
from apps.scheduling.models import Appointment, Reminder

pytestmark = pytest.mark.django_db


def test_interpretarea_nu_salveaza_nimic_in_aplicatie(user):
    services.interpret(user, "Notează că trebuie să sun la bancă")

    assert Note.objects.for_user(user).count() == 0
    assert IntentDraft.objects.for_user(user).count() == 1


def test_confirmarea_creeaza_notita(user):
    draft = services.interpret(user, "Notează că trebuie să sun la bancă")
    kind, pk = drafts.apply(draft)

    assert kind == "notita"
    note = Note.objects.get(pk=pk)
    assert note.owner == user
    assert note.source == "voice"


def test_confirmarea_de_doua_ori_nu_creeaza_duplicat(user):
    draft = services.interpret(user, "Notează ideea pentru campanie")
    first = drafts.apply(draft)
    second = drafts.apply(draft)

    assert first == second
    assert Note.objects.for_user(user).count() == 1


def test_programarea_creeaza_si_alarma(user):
    draft = services.interpret(
        user, "Programează o întâlnire mâine la 10 cu titlul Sincronizare"
    )
    kind, pk = drafts.apply(draft)

    appointment = Appointment.objects.get(pk=pk)
    assert kind == "programare"
    assert appointment.reminders.count() == 1
    assert appointment.reminders.first().offset_minutes == 30


def test_valorile_editate_de_utilizator_au_prioritate(user):
    draft = services.interpret(user, "Notează ceva")
    drafts.apply(draft, overrides={"title": "Titlu corectat de utilizator"})

    assert Note.objects.for_user(user).first().title == "Titlu corectat de utilizator"


def test_schita_expirata_nu_se_mai_poate_confirma(user):
    draft = services.interpret(user, "Notează ceva")
    IntentDraft.objects.filter(pk=draft.pk).update(
        expires_at=timezone.now() - timezone.timedelta(minutes=1)
    )
    draft.refresh_from_db()

    with pytest.raises(drafts.DraftError):
        drafts.apply(draft)


def test_schita_abandonata_nu_se_mai_poate_confirma(user):
    draft = services.interpret(user, "Notează ceva")
    draft.status = IntentDraft.Status.DISCARDED
    draft.save(update_fields=["status"])

    with pytest.raises(drafts.DraftError):
        drafts.apply(draft)


def test_modificarea_schimba_obiectul_tinta(user, reminder_factory, at):
    reminder = reminder_factory(user, title="Plată factură", day_offset=5, hour=9)
    draft = services.interpret(
        user, "Mută la ora 15", mode="edit", target_kind="alarma", target_id=reminder.pk
    )
    drafts.apply(draft)

    reminder.refresh_from_db()
    assert timezone.localtime(reminder.remind_at).hour == 15


def test_stergerea_prin_schita_muta_in_cos(user, note_factory):
    note = note_factory(user, title="De șters")
    draft = services.interpret(user, "Șterge notița De șters")
    drafts.apply(draft)

    assert not Note.objects.filter(pk=note.pk).exists()
    assert Note.all_objects.get(pk=note.pk).deleted_at is not None


def test_endpointul_de_confirmare_refuza_schita_neclara(auth_client, user):
    draft = services.interpret(user, "Pune-mi o alarmă")

    response = auth_client.post(
        reverse("assistant:draft_confirm", args=[draft.uid]),
        {"intent": "create_reminder", "title": "X"},
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 409
    assert Reminder.objects.for_user(user).count() == 0


def test_endpointul_de_stergere_cere_doua_apasari(auth_client, user, note_factory):
    note = note_factory(user, title="Lista cumpărături")
    draft = services.interpret(user, "Șterge notița Lista cumpărături")
    url = reverse("assistant:draft_confirm", args=[draft.uid])

    first = auth_client.post(url, {}, headers={"HX-Request": "true"})
    assert first.status_code == 200
    assert Note.objects.filter(pk=note.pk).exists()

    second = auth_client.post(url, {"confirmare": "da"}, headers={"HX-Request": "true"})
    assert second.status_code == 204
    assert not Note.objects.filter(pk=note.pk).exists()


def test_clarificarea_prin_alegerea_unui_candidat(auth_client, user, note_factory):
    note_factory(user, title="Ședință proiect Alpha")
    note_factory(user, title="Ședință proiect Beta")
    draft = services.interpret(user, "Șterge notița Ședință proiect")
    candidate = draft.candidates[0]

    auth_client.post(
        reverse("assistant:draft_clarify", args=[draft.uid]),
        {"candidat": f"{candidate['kind']}:{candidate['pk']}"},
        headers={"HX-Request": "true"},
    )

    draft.refresh_from_db()
    assert draft.target_id == candidate["pk"]
    assert draft.status == IntentDraft.Status.DRAFT


def test_schita_altui_utilizator_nu_este_accesibila(other_client, user):
    draft = services.interpret(user, "Notează ceva")

    response = other_client.get(reverse("assistant:draft", args=[draft.uid]))

    assert response.status_code == 404
