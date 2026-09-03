"""Taskuri de intretinere: purjarea cosului si a fisierelor temporare."""

from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from apps.core.files import delete_associated_files
from apps.core.models import AuditLog
from apps.core.registry import soft_delete_models

logger = logging.getLogger("voicetask.core")


@shared_task(name="core.purge_trashed", ignore_result=True)
def purge_trashed(retention_days: int | None = None) -> int:
    """Sterge definitiv obiectele aflate in cos de peste 30 de zile."""
    days = retention_days if retention_days is not None else settings.TRASH_RETENTION_DAYS
    cutoff = timezone.now() - timedelta(days=days)
    purged = 0
    for model in soft_delete_models():
        queryset = model.all_objects.filter(deleted_at__lt=cutoff)
        for obj in queryset.iterator(chunk_size=200):
            delete_associated_files(obj)
            owner = getattr(obj, "owner", None)
            label = obj._meta.label
            pk = obj.pk
            obj.hard_delete()
            AuditLog.objects.create(
                user=owner,
                action=AuditLog.Action.PURGE,
                object_label=label,
                object_id=str(pk),
                detail={"retention_days": days},
            )
            purged += 1
    if purged:
        logger.info("purge_trashed: %d obiecte sterse definitiv", purged)
    return purged


@shared_task(name="core.purge_expired_drafts", ignore_result=True)
def purge_expired_drafts() -> int:
    """Schitele neconfirmate expira; nu tinem transcrieri mai mult decat e nevoie."""
    from apps.assistant.models import IntentDraft

    deleted, _ = IntentDraft.objects.filter(expires_at__lt=timezone.now()).delete()
    return deleted


@shared_task(name="core.purge_old_media", ignore_result=True)
def purge_old_media() -> int:
    """Sterge inregistrarile audio vechi si fisierele audio de rezumat orfane."""
    from apps.assistant.models import VoiceCapture

    cutoff = timezone.now() - timedelta(days=settings.VOICE_AUDIO_RETENTION_DAYS)
    removed = 0
    for capture in VoiceCapture.all_objects.filter(
        created_at__lt=cutoff, audio__isnull=False
    ).exclude(audio="").iterator(chunk_size=100):
        capture.audio.delete(save=False)
        capture.audio = ""
        capture.save(update_fields=["audio"])
        removed += 1
    return removed
