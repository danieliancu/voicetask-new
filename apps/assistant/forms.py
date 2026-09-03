"""Formularul schitei: ultimul pas editabil inainte de salvare."""

from __future__ import annotations

from django import forms

from apps.assistant.schemas import Intent, IntentResult

INTENT_CHOICES = (
    (Intent.CREATE_NOTE, "Notă"),
    (Intent.CREATE_APPOINTMENT, "Programare"),
    (Intent.CREATE_REMINDER, "Alarmă"),
    (Intent.FOLLOW_UP_EMAIL, "Email"),
)

REMINDER_OFFSETS = (
    ("", "Fără alarmă"),
    (0, "La momentul evenimentului"),
    (10, "Cu 10 minute înainte"),
    (30, "Cu 30 de minute înainte"),
    (60, "Cu o oră înainte"),
    (1440, "Cu o zi înainte"),
)


class DraftForm(forms.Form):
    """Campurile vin din schita; utilizatorul le poate schimba pe toate."""

    intent = forms.ChoiceField(label="Tip", choices=INTENT_CHOICES)
    title = forms.CharField(label="Titlu", max_length=200)
    description = forms.CharField(
        label="Detalii", required=False, widget=forms.Textarea(attrs={"rows": 3})
    )
    date = forms.DateField(
        label="Dată", required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    start_time = forms.TimeField(
        label="Ora de început", required=False, widget=forms.TimeInput(attrs={"type": "time"})
    )
    end_time = forms.TimeField(
        label="Ora de final", required=False, widget=forms.TimeInput(attrs={"type": "time"})
    )
    location = forms.CharField(label="Locație", required=False, max_length=200)
    person = forms.CharField(label="Persoană", required=False, max_length=120)
    reminder_offset = forms.TypedChoiceField(
        label="Alarmă", choices=REMINDER_OFFSETS, coerce=int, required=False, empty_value=None
    )

    def __init__(self, *args, draft=None, **kwargs):
        self.draft = draft
        super().__init__(*args, **kwargs)
        if draft is not None and not self.is_bound:
            result = IntentResult.model_validate(draft.payload)
            self.initial.update(
                {
                    "intent": result.intent,
                    "title": result.title or draft.source_text[:200],
                    "description": result.description or "",
                    "date": result.date,
                    "start_time": result.start_time,
                    "end_time": result.end_time,
                    "location": result.location or "",
                    "person": result.person or "",
                    "reminder_offset": result.reminder_offset,
                }
            )
        if draft is not None and draft.intent in {Intent.UPDATE_ITEM, Intent.DELETE_ITEM}:
            self.fields["intent"].choices = [
                (draft.intent, "Modificare" if draft.intent == Intent.UPDATE_ITEM else "Ștergere")
            ]

    def clean(self):
        data = super().clean()
        intent = data.get("intent")
        if intent in {Intent.CREATE_APPOINTMENT, Intent.CREATE_REMINDER} and not data.get("date"):
            self.add_error("date", "Alege o dată.")
        start, end = data.get("start_time"), data.get("end_time")
        if start and end and end < start:
            self.add_error("end_time", "Ora de final nu poate fi înaintea celei de început.")
        return data

    def to_overrides(self) -> dict:
        """Valorile editate, in formatul asteptat de schema."""
        data = self.cleaned_data
        return {
            "intent": data["intent"],
            "title": data["title"],
            "description": data.get("description") or None,
            "date": data["date"].isoformat() if data.get("date") else None,
            "start_time": data["start_time"].isoformat() if data.get("start_time") else None,
            "end_time": data["end_time"].isoformat() if data.get("end_time") else None,
            "location": data.get("location") or None,
            "person": data.get("person") or None,
            "reminder_offset": data.get("reminder_offset"),
        }


class TextCommandForm(forms.Form):
    """Alternativa scrisa, pentru cand microfonul nu este disponibil."""

    text = forms.CharField(
        label="Scrie comanda",
        max_length=500,
        widget=forms.Textarea(
            attrs={"rows": 3, "placeholder": "Ex.: Programare mâine la 10 cu Ana"}
        ),
    )
    mode = forms.CharField(required=False, widget=forms.HiddenInput)
