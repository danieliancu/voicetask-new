"""Formularul editabil cu datele extrase din document.

Campurile sunt precompletate din OCR, dar nimic nu se salveaza pana cand
utilizatorul nu apasa „Salvează". Fiecare camp isi poarta scorul de incredere,
folosit de sablon ca sa marcheze vizual valorile nesigure.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from django import forms
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core.enums import Source
from apps.documents.models import ScannedDocument

ACTION_CHOICES = (
    ("reminder", "Alarmă pentru data limită"),
    ("appointment", "Programare în calendar"),
    ("note", "Doar notiță"),
)

REMINDER_OFFSETS = (
    (0, "În ziua respectivă"),
    (1440, "Cu o zi înainte"),
    (2880, "Cu două zile înainte"),
    (10080, "Cu o săptămână înainte"),
)


class ExtractionConfirmForm(forms.Form):
    title = forms.CharField(label="Titlu", max_length=200)
    document_type = forms.ChoiceField(
        label="Tip document", choices=ScannedDocument.DocumentType.choices
    )
    due_date = forms.DateField(
        label="Dată limită",
        required=False,
        # Vezi nota din `apps/assistant/forms.py`: fara `format`, `<input
        # type="date">` primeste o valoare localizata pe care nu o poate citi.
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    event_time = forms.TimeField(
        label="Oră", required=False, widget=forms.TimeInput(attrs={"type": "time"})
    )
    amount = forms.DecimalField(label="Sumă", required=False, max_digits=12, decimal_places=2)
    currency = forms.CharField(label="Monedă", required=False, max_length=8)
    location = forms.CharField(label="Locație", required=False, max_length=200)
    person = forms.CharField(label="Persoană / companie", required=False, max_length=200)
    notes = forms.CharField(
        label="Notițe", required=False, widget=forms.Textarea(attrs={"rows": 3})
    )
    action = forms.ChoiceField(label="Ce să creez", choices=ACTION_CHOICES)
    reminder_offset = forms.TypedChoiceField(
        label="Alarmă", choices=REMINDER_OFFSETS, coerce=int, required=False, initial=1440
    )

    def __init__(self, *args, document: ScannedDocument, user=None, **kwargs):
        self.document = document
        self.user = user
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial.update(self._initial_from_document())

    def _initial_from_document(self) -> dict:
        doc = self.document
        due = _as_date(doc.field("due_date")) or _as_date(doc.field("event_date"))
        return {
            "title": doc.title or "",
            "document_type": doc.document_type,
            "due_date": due,
            "event_time": _as_time(doc.field("time")),
            "amount": doc.field("amount"),
            "currency": doc.field("currency") or "",
            "location": doc.field("location") or doc.field("address") or "",
            "person": doc.field("person") or doc.field("company") or "",
            "action": doc.field("suggested_action") or "note",
            "reminder_offset": 1440,
        }

    def field_confidence(self, name: str) -> float:
        """Increderea OCR pentru campul din formular, mapata pe numele modelului."""
        mapping = {
            "due_date": ("due_date", "event_date"),
            "event_time": ("time",),
            "amount": ("amount",),
            "currency": ("currency",),
            "location": ("location", "address"),
            "person": ("person", "company"),
            "title": ("title",),
            "document_type": ("document_type",),
        }
        return max(
            (self.document.confidence(source) for source in mapping.get(name, ())),
            default=1.0,
        )

    def uncertain_fields(self) -> list[str]:
        threshold = settings.OCR_FIELD_CONFIDENCE_WARN
        return [
            name
            for name in self.fields
            if self.field_confidence(name) < threshold and self.field_confidence(name) > 0
        ]

    def clean(self):
        data = super().clean()
        action = data.get("action")
        if action in {"reminder", "appointment"} and not data.get("due_date"):
            self.add_error(
                "due_date",
                'Alege o dată sau schimbă acțiunea în „Doar notiță”.',
            )
        return data

    @transaction.atomic
    def save(self) -> dict:
        """Creeaza obiectele confirmate si le leaga de document."""
        from apps.notes.models import Note
        from apps.scheduling.models import Appointment, Reminder

        data = self.cleaned_data
        created: dict[str, object] = {}
        owner = self.user or self.document.owner

        self.document.title = data["title"]
        self.document.document_type = data["document_type"]

        body_lines = []
        if data.get("amount"):
            body_lines.append(f"Sumă: {data['amount']} {data.get('currency', '')}".strip())
        if data.get("person"):
            body_lines.append(f"Emitent: {data['person']}")
        if data.get("location"):
            body_lines.append(f"Locație: {data['location']}")
        if data.get("notes"):
            body_lines.append(data["notes"])

        note = Note.objects.create(
            owner=owner,
            title=data["title"],
            content="\n".join(body_lines),
            source=Source.SCAN,
            source_document=self.document,
        )
        created["notiță"] = note

        if data["action"] == "appointment":
            starts_at = _combine(data["due_date"], data.get("event_time") or time(9, 0))
            appointment = Appointment.objects.create(
                owner=owner,
                title=data["title"],
                description="\n".join(body_lines),
                location=data.get("location", ""),
                starts_at=starts_at,
                ends_at=starts_at + timedelta(hours=1),
                source=Source.SCAN,
                source_document=self.document,
            )
            created["programare"] = appointment
            offset = data.get("reminder_offset") or 0
            reminder = Reminder.objects.create(
                owner=owner,
                title=data["title"],
                remind_at=starts_at - timedelta(minutes=offset),
                offset_minutes=offset,
                appointment=appointment,
                document=self.document,
                source=Source.SCAN,
            )
            created["alarmă"] = reminder

        elif data["action"] == "reminder":
            offset = data.get("reminder_offset") or 0
            due_at = _combine(data["due_date"], data.get("event_time") or time(9, 0))
            reminder = Reminder.objects.create(
                owner=owner,
                title=data["title"],
                description="\n".join(body_lines),
                remind_at=due_at - timedelta(minutes=offset),
                offset_minutes=offset,
                note=note,
                document=self.document,
                source=Source.SCAN,
            )
            created["alarmă"] = reminder

        return created


def _as_date(value):
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _as_time(value):
    if isinstance(value, time):
        return value
    try:
        return time.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _combine(day: date, at: time):
    return timezone.make_aware(
        datetime.combine(day, at), timezone.get_current_timezone()
    )
