"""Invalidarea rezumatului cand se schimba datele din care a fost construit.

Nu regeneram sincron: marcam rezumatul ca invalid, iar urmatoarea afisare (sau
taskul Celery) il reconstruieste. Asa o salvare de notita nu plateste costul unui
apel TTS.
"""

from __future__ import annotations

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.daily_brief.models import DailyBrief

#: Modelele care intra in instantaneu. Vezi `snapshot.build_snapshot`.
WATCHED = (
    "scheduling.Appointment",
    "scheduling.Reminder",
    "documents.ScannedDocument",
    "integrations.EmailReference",
)


def _invalidate_for(instance) -> None:
    owner_id = getattr(instance, "owner_id", None)
    if owner_id is None:
        return
    DailyBrief.objects.filter(owner_id=owner_id, status=DailyBrief.Status.READY).update(
        status=DailyBrief.Status.PENDING
    )


@receiver(post_save, dispatch_uid="invalideaza_rezumat_la_salvare")
def on_save(sender, instance, **kwargs):
    if f"{sender._meta.app_label}.{sender._meta.object_name}" in WATCHED:
        _invalidate_for(instance)


@receiver(post_delete, dispatch_uid="invalideaza_rezumat_la_stergere")
def on_delete(sender, instance, **kwargs):
    if f"{sender._meta.app_label}.{sender._meta.object_name}" in WATCHED:
        _invalidate_for(instance)
