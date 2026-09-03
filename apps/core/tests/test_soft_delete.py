"""Soft delete, restaurare in cascada si purjarea dupa 30 de zile."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.core.tasks import purge_trashed
from apps.notes.models import ChecklistItem, Note

pytestmark = pytest.mark.django_db


def test_stergerea_muta_in_cos_nu_sterge_randul(user, note_factory):
    note = note_factory(user)
    note.delete()

    assert Note.objects.filter(pk=note.pk).count() == 0
    assert Note.all_objects.filter(pk=note.pk).count() == 1
    assert Note.all_objects.get(pk=note.pk).deleted_at is not None


def test_stergerea_cascadeaza_pe_elementele_listei(user, note_factory):
    note = note_factory(user)
    ChecklistItem.objects.create(note=note, text="Lapte")
    ChecklistItem.objects.create(note=note, text="Ouă")

    note.delete()

    assert ChecklistItem.objects.filter(note=note).count() == 0
    assert ChecklistItem.all_objects.filter(note=note, deleted_by_cascade=True).count() == 2


def test_restaurarea_readuce_exact_ce_a_sters(user, note_factory):
    note = note_factory(user)
    ramane_sters = ChecklistItem.objects.create(note=note, text="Șters separat")
    ramane_sters.delete()
    ChecklistItem.objects.create(note=note, text="Lapte")

    note.delete()
    note.restore()

    assert Note.objects.filter(pk=note.pk).exists()
    # Elementul sters individual ramane in cos; doar cascada se restaureaza.
    assert ChecklistItem.objects.filter(note=note).count() == 1
    assert ChecklistItem.all_objects.get(pk=ramane_sters.pk).deleted_at is not None


def test_stergerea_in_masa_este_tot_soft(user, note_factory):
    note_factory(user, title="Unu")
    note_factory(user, title="Doi")

    Note.objects.for_user(user).delete()

    assert Note.objects.for_user(user).count() == 0
    assert Note.all_objects.filter(owner=user).count() == 2


def test_managerul_invers_exclude_cosul(user, note_factory):
    note = note_factory(user)
    note.delete()
    assert user.notes_note_set.count() == 0


def test_purjarea_sterge_definitiv_dupa_termen(user, note_factory):
    recenta = note_factory(user, title="Recentă")
    veche = note_factory(user, title="Veche")
    recenta.delete()
    veche.delete()

    Note.all_objects.filter(pk=veche.pk).update(
        deleted_at=timezone.now() - timedelta(days=31)
    )
    purged = purge_trashed()

    assert purged == 1
    assert not Note.all_objects.filter(pk=veche.pk).exists()
    assert Note.all_objects.filter(pk=recenta.pk).exists()


def test_purjarea_lasa_intacte_obiectele_active(user, note_factory):
    note_factory(user)
    assert purge_trashed() == 0
    assert Note.objects.for_user(user).count() == 1


def test_hard_delete_ocoleste_cosul(user, note_factory):
    note = note_factory(user)
    note.hard_delete()
    assert not Note.all_objects.filter(pk=note.pk).exists()
