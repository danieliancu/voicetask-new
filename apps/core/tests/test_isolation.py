"""Izolarea datelor intre utilizatori si accesul anonim."""

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_lista_nu_arata_datele_altui_utilizator(auth_client, other_user, note_factory, user):
    note_factory(user, title="A mea")
    note_factory(other_user, title="A altcuiva")

    response = auth_client.get(reverse("notes:list"))

    assert b"A mea" in response.content
    assert "A altcuiva" not in response.content.decode()


@pytest.mark.parametrize(
    "route,factory_name",
    [
        ("notes:detail", "note_factory"),
        ("notes:update", "note_factory"),
        ("scheduling:detail", "appointment_factory"),
        ("scheduling:update", "appointment_factory"),
        ("scheduling:reminder_detail", "reminder_factory"),
        ("documents:detail", "document_factory"),
    ],
)
def test_obiectul_altui_utilizator_da_404(auth_client, other_user, request, route, factory_name):
    """404, nu 403: nu confirmam nici macar existenta obiectului altcuiva."""
    factory = request.getfixturevalue(factory_name)
    obj = factory(other_user)

    response = auth_client.get(reverse(route, args=[obj.pk]))

    assert response.status_code == 404


@pytest.mark.parametrize(
    "route",
    [
        "core:home",
        "core:edit_hub",
        "core:delete_hub",
        "core:trash",
        "notes:list",
        "notes:create",
        "scheduling:calendar",
        "scheduling:reminder_list",
        "documents:list",
        "documents:scan",
        "search:index",
        "assistant:capture",
        "daily_brief:today",
        "notifications:inbox",
        "integrations:status",
        "accounts:preferences",
    ],
)
def test_paginile_cer_autentificare(client, route):
    response = client.get(reverse(route))
    assert response.status_code == 302
    assert "/conturi/intra/" in response.url


def test_stergerea_nu_atinge_obiectul_altui_utilizator(auth_client, other_user, note_factory):
    from apps.notes.models import Note

    note = note_factory(other_user, title="A altcuiva")

    response = auth_client.post(
        reverse("core:delete_execute"), {"element": f"notita:{note.pk}"}
    )

    assert response.status_code == 302
    assert Note.objects.filter(pk=note.pk).exists()


def test_restaurarea_nu_atinge_cosul_altui_utilizator(auth_client, other_user, note_factory):
    from apps.notes.models import Note

    note = note_factory(other_user)
    note.delete()

    auth_client.post(reverse("core:trash_restore"), {"element": f"notita:{note.pk}"})

    assert Note.all_objects.get(pk=note.pk).deleted_at is not None


def test_audio_rezumatului_nu_este_accesibil_altcuiva(auth_client, other_user):
    from apps.daily_brief.services import get_or_create_brief

    brief = get_or_create_brief(other_user)

    response = auth_client.get(reverse("daily_brief:audio", args=[brief.pk]))

    assert response.status_code == 404
