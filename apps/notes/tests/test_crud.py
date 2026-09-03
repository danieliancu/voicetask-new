"""CRUD pentru notite."""

import pytest
from django.urls import reverse

from apps.notes.models import ChecklistItem, Note, NoteCategory

pytestmark = pytest.mark.django_db


def test_creare(auth_client, user):
    response = auth_client.post(
        reverse("notes:create"), {"title": "Idei campanie", "content": "Moodboard"}
    )

    assert response.status_code == 302
    note = Note.objects.for_user(user).get()
    assert note.title == "Idei campanie"
    assert note.owner == user


def test_creare_fara_titlu_esueaza(auth_client, user):
    response = auth_client.post(reverse("notes:create"), {"title": "", "content": "X"})

    assert response.status_code == 200
    assert Note.objects.for_user(user).count() == 0


def test_editare(auth_client, user, note_factory):
    note = note_factory(user, title="Vechi")

    auth_client.post(reverse("notes:update", args=[note.pk]), {"title": "Nou", "content": ""})

    note.refresh_from_db()
    assert note.title == "Nou"


def test_stergerea_prin_get_doar_arata_dialogul(auth_client, user, note_factory):
    note = note_factory(user)

    response = auth_client.get(reverse("notes:delete", args=[note.pk]))

    assert response.status_code == 200
    assert b"<dialog" in response.content
    assert Note.objects.filter(pk=note.pk).exists()


def test_stergerea_prin_post_muta_in_cos(auth_client, user, note_factory):
    note = note_factory(user)

    auth_client.post(reverse("notes:delete", args=[note.pk]))

    assert not Note.objects.filter(pk=note.pk).exists()
    assert Note.all_objects.filter(pk=note.pk).exists()


def test_fixarea_notitei(auth_client, user, note_factory):
    note = note_factory(user)

    auth_client.post(reverse("notes:toggle_pin", args=[note.pk]))
    note.refresh_from_db()
    assert note.is_pinned

    auth_client.post(reverse("notes:toggle_pin", args=[note.pk]))
    note.refresh_from_db()
    assert not note.is_pinned


def test_bifarea_unui_element_de_lista(auth_client, user, note_factory):
    note = note_factory(user)
    item = ChecklistItem.objects.create(note=note, text="Lapte")

    auth_client.post(reverse("notes:toggle_item", args=[note.pk, item.pk]))

    item.refresh_from_db()
    assert item.is_done


def test_categoria_din_formular_este_limitata_la_utilizator(user, other_user):
    from apps.notes.forms import NoteForm

    a_mea = NoteCategory.objects.create(owner=user, name="Muncă", slug="munca")
    NoteCategory.objects.create(owner=other_user, name="Altele", slug="altele")

    form = NoteForm(user=user)

    assert list(form.fields["category"].queryset) == [a_mea]


def test_textul_de_cautare_este_normalizat_la_salvare(user, note_factory):
    note = note_factory(user, title="Ședință cu părinții")
    assert "sedinta" in note.match_text
    assert "parintii" in note.match_text


def test_filtrarea_dupa_categorie(auth_client, user, note_factory):
    categorie = NoteCategory.objects.create(owner=user, name="Muncă", slug="munca")
    note_factory(user, title="De muncă", category=categorie)
    note_factory(user, title="Personală")

    response = auth_client.get(reverse("notes:list"), {"categorie": "munca"})
    content = response.content.decode()

    assert "De muncă" in content
    assert "Personală" not in content
