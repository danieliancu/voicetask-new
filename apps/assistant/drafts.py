"""Transformarea unei schite confirmate in obiecte reale.

Aceasta este singura cale prin care o comanda vocala scrie in baza de date.
Confirmarea este idempotenta: o a doua apasare pe „Salvează" nu creeaza duplicate.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from django.db import transaction
from django.utils import timezone

from apps.assistant.models import IntentDraft
from apps.assistant.schemas import Intent, IntentResult
from apps.core.enums import ItemKind, Source
from apps.core.models import AuditLog
from apps.core.registry import model_for_kind

DEFAULT_TIME = time(9, 0)


class DraftError(Exception):
    """Schita nu poate fi aplicata in starea curenta."""


def _aware(day, at: time | None):
    return timezone.make_aware(
        datetime.combine(day, at or DEFAULT_TIME), timezone.get_current_timezone()
    )


@transaction.atomic
def apply(draft: IntentDraft, *, overrides: dict | None = None) -> tuple[str, int]:
    """Aplica schita si returneaza (tip, id) al obiectului rezultat."""
    locked = IntentDraft.objects.select_for_update().get(pk=draft.pk)
    if locked.status == IntentDraft.Status.CONFIRMED:
        # Deja confirmata: returnam acelasi rezultat, fara sa cream nimic nou.
        return locked.result_kind, locked.result_id
    if locked.status == IntentDraft.Status.DISCARDED:
        raise DraftError("Schița a fost abandonată.")
    if locked.is_expired:
        raise DraftError("Schița a expirat. Reia comanda.")

    payload = {**locked.payload, **(overrides or {})}
    result = IntentResult.model_validate(payload)

    handler = {
        Intent.CREATE_NOTE: _create_note,
        Intent.CREATE_APPOINTMENT: _create_appointment,
        Intent.CREATE_REMINDER: _create_reminder,
        Intent.FOLLOW_UP_EMAIL: _follow_up_email,
        Intent.UPDATE_ITEM: _update_item,
        Intent.DELETE_ITEM: _delete_item,
    }.get(result.intent)

    if handler is None:
        raise DraftError("Această comandă nu poate fi salvată.")

    kind, pk = handler(locked, result)

    locked.status = IntentDraft.Status.CONFIRMED
    locked.result_kind = kind
    locked.result_id = pk
    locked.payload = result.model_dump(mode="json")
    locked.save(update_fields=["status", "result_kind", "result_id", "payload", "updated_at"])
    return kind, pk


def _create_note(draft: IntentDraft, result: IntentResult) -> tuple[str, int]:
    from apps.notes.models import Note

    note = Note.objects.create(
        owner=draft.owner,
        title=result.title or (draft.source_text[:200] or "Notiță"),
        content=result.description or "",
        source=Source.VOICE,
    )
    return ItemKind.NOTE, note.pk


def _create_appointment(draft: IntentDraft, result: IntentResult) -> tuple[str, int]:
    from apps.scheduling.models import Appointment
    from apps.scheduling.services import sync_appointment_reminder

    if result.date is None:
        raise DraftError("Programarea are nevoie de o dată.")
    starts_at = _aware(result.date, result.start_time)
    ends_at = (
        _aware(result.date, result.end_time)
        if result.end_time
        else starts_at + timedelta(hours=1)
    )

    appointment = Appointment.objects.create(
        owner=draft.owner,
        title=result.title or "Programare",
        description=result.description or "",
        location=result.location or "",
        starts_at=starts_at,
        ends_at=ends_at,
        source=Source.VOICE,
    )
    sync_appointment_reminder(appointment, result.reminder_offset, source=Source.VOICE)
    return ItemKind.APPOINTMENT, appointment.pk


def _create_reminder(draft: IntentDraft, result: IntentResult) -> tuple[str, int]:
    from apps.scheduling.models import Reminder

    if result.date is None:
        raise DraftError("Alarma are nevoie de o dată.")
    reminder = Reminder.objects.create(
        owner=draft.owner,
        title=result.title or "Alarmă",
        description=result.description or "",
        remind_at=_aware(result.date, result.start_time),
        source=Source.VOICE,
    )
    return ItemKind.REMINDER, reminder.pk


def _follow_up_email(draft: IntentDraft, result: IntentResult) -> tuple[str, int]:
    from apps.integrations.models import EmailReference

    queryset = EmailReference.objects.for_user(draft.owner)
    if result.person:
        from apps.search.normalize import normalize

        needle = normalize(result.person)
        queryset = queryset.filter(match_text__contains=needle)
    email = queryset.order_by("-received_at").first()
    if email is None:
        raise DraftError("Nu am găsit emailul la care te referi.")

    email.status = EmailReference.Status.FOLLOW_UP
    email.follow_up_at = (
        _aware(result.date, result.start_time)
        if result.date
        else timezone.now() + timedelta(days=1)
    )
    email.save(update_fields=["status", "follow_up_at", "updated_at"])
    return ItemKind.EMAIL, email.pk


#: Ce campuri din schita se pot aplica peste fiecare tip de obiect.
UPDATE_FIELDS = {
    ItemKind.NOTE: {"title": "title", "description": "content"},
    ItemKind.APPOINTMENT: {"title": "title", "description": "description", "location": "location"},
    ItemKind.REMINDER: {"title": "title", "description": "description"},
}


def _update_item(draft: IntentDraft, result: IntentResult) -> tuple[str, int]:
    kind = result.target_kind or draft.target_kind
    pk = result.target_id or draft.target_id
    if not kind or not pk:
        raise DraftError("Nu știu ce element să modific.")

    model = model_for_kind(kind)
    if model is None:
        raise DraftError("Tip de element necunoscut.")
    obj = model.objects.filter(pk=pk, owner=draft.owner).first()
    if obj is None:
        raise DraftError("Elementul nu mai există.")

    changed: list[str] = []
    for source_field, target_field in UPDATE_FIELDS.get(kind, {}).items():
        value = getattr(result, source_field, None)
        if value:
            setattr(obj, target_field, value)
            changed.append(target_field)

    if kind == ItemKind.APPOINTMENT and result.date:
        current_time = timezone.localtime(obj.starts_at).time()
        starts_at = _aware(result.date, result.start_time or current_time)
        duration = obj.duration or timedelta(hours=1)
        obj.starts_at = starts_at
        obj.ends_at = starts_at + duration
        changed += ["starts_at", "ends_at"]
    elif kind == ItemKind.REMINDER and (result.date or result.start_time):
        current = timezone.localtime(obj.remind_at)
        obj.remind_at = _aware(result.date or current.date(), result.start_time or current.time())
        obj.status = obj.Status.SCHEDULED
        obj.notification_sent_at = None
        changed += ["remind_at", "status", "notification_sent_at"]

    if kind == ItemKind.REMINDER and result.reminder_offset is not None and obj.appointment_id:
        obj.offset_minutes = result.reminder_offset
        obj.remind_at = obj.appointment.starts_at - timedelta(minutes=result.reminder_offset)
        changed += ["offset_minutes", "remind_at"]

    if not changed:
        raise DraftError("Nu am înțeles ce trebuie modificat.")

    obj.save(update_fields=[*set(changed), "updated_at"])
    return kind, obj.pk


def _delete_item(draft: IntentDraft, result: IntentResult) -> tuple[str, int]:
    kind = result.target_kind or draft.target_kind
    pk = result.target_id or draft.target_id
    if not kind or not pk:
        raise DraftError("Nu știu ce element să șterg.")

    model = model_for_kind(kind)
    obj = model.objects.filter(pk=pk, owner=draft.owner).first() if model else None
    if obj is None:
        raise DraftError("Elementul nu mai există.")

    obj.delete()
    AuditLog.objects.create(
        user=draft.owner,
        action=AuditLog.Action.DELETE,
        object_label=model._meta.label,
        object_id=str(pk),
        detail={"sursa": "comanda_vocala"},
    )
    return kind, pk
