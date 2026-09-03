"""Ecranul Șterge: confirmare obligatorie, soft delete, recuperare din coș."""

import pytest
from django.urls import reverse

from apps.core.models import AuditLog
from apps.notes.models import Note
from apps.scheduling.models import Appointment

pytestmark = pytest.mark.django_db


def test_ecranul_listeaza_elementele_si_filtrele(
    auth_client, user, note_factory, appointment_factory
):
    note_factory(user, title="Notiță de șters")
    appointment_factory(user, title="Programare de șters")

    response = auth_client.get(reverse("core:delete_hub"))
    content = response.content.decode()

    assert "Notiță de șters" in content
    assert "Programare de șters" in content
    assert "Evenimente" in content
    assert "Documente" in content


def test_filtrarea_pe_tip(auth_client, user, note_factory, appointment_factory):
    note_factory(user, title="Notiță de șters")
    appointment_factory(user, title="Programare de șters")

    response = auth_client.get(reverse("core:delete_hub"), {"tip": "evenimente"})
    content = response.content.decode()

    assert "Programare de șters" in content
    assert "Notiță de șters" not in content


def test_confirmarea_arata_dialogul_si_nu_sterge(auth_client, user, note_factory):
    note = note_factory(user)

    response = auth_client.post(
        reverse("core:delete_confirm"), {"element": f"notita:{note.pk}"}
    )
    content = response.content.decode()

    assert "<dialog" in content
    assert "30 de zile" in content
    assert Note.objects.filter(pk=note.pk).exists()


def test_executarea_muta_in_cos(auth_client, user, note_factory):
    note = note_factory(user)

    response = auth_client.post(
        reverse("core:delete_execute"), {"element": f"notita:{note.pk}"}
    )

    assert response.status_code == 302
    assert not Note.objects.filter(pk=note.pk).exists()
    assert Note.all_objects.get(pk=note.pk).deleted_at is not None


def test_stergerea_multipla(auth_client, user, note_factory, appointment_factory):
    note = note_factory(user)
    appointment = appointment_factory(user)

    auth_client.post(
        reverse("core:delete_execute"),
        {"element": [f"notita:{note.pk}", f"programare:{appointment.pk}"]},
    )

    assert Note.objects.filter(pk=note.pk).count() == 0
    assert Appointment.objects.filter(pk=appointment.pk).count() == 0


def test_stergerea_se_inregistreaza_in_audit(auth_client, user, note_factory):
    note = note_factory(user)

    auth_client.post(reverse("core:delete_execute"), {"element": f"notita:{note.pk}"})

    assert AuditLog.objects.filter(
        user=user, action=AuditLog.Action.DELETE, object_id=str(note.pk)
    ).exists()


def test_get_ul_nu_sterge_niciodata(auth_client, user, note_factory):
    note = note_factory(user)

    response = auth_client.get(reverse("core:delete_execute"))

    assert response.status_code == 405
    assert Note.objects.filter(pk=note.pk).exists()


def test_selectia_goala_nu_face_nimic(auth_client, user, note_factory):
    note_factory(user)
    response = auth_client.post(reverse("core:delete_execute"), {})
    assert response.status_code == 302
    assert Note.objects.count() == 1


def test_identificatorul_invalid_este_ignorat(auth_client, user, note_factory):
    note = note_factory(user)

    auth_client.post(
        reverse("core:delete_execute"),
        {"element": ["tip-inexistent:1", "notita:abc", f"notita:{note.pk}"]},
    )

    assert not Note.objects.filter(pk=note.pk).exists()


def test_cosul_arata_data_de_expirare(auth_client, user, note_factory):
    note = note_factory(user, title="În coș")
    note.delete()

    response = auth_client.get(reverse("core:trash"))
    content = response.content.decode()

    assert "În coș" in content
    assert "30 de zile" in content


def test_restaurarea_din_cos(auth_client, user, note_factory):
    note = note_factory(user)
    note.delete()

    auth_client.post(reverse("core:trash_restore"), {"element": f"notita:{note.pk}"})

    assert Note.objects.filter(pk=note.pk).exists()
    assert AuditLog.objects.filter(action=AuditLog.Action.RESTORE).exists()


def test_stergerea_unei_programari_sincronizate_avertizeaza(auth_client, user, appointment_factory):
    appointment = appointment_factory(user, external_calendar_id="ext-1")

    response = auth_client.get(reverse("scheduling:delete", args=[appointment.pk]))

    assert "Google Calendar" in response.content.decode()
