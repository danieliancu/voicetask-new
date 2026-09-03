"""Formularul schitei: ultimul pas editabil inainte de salvare."""

from __future__ import annotations

from django import forms
from django.utils import timezone

from apps.assistant.schemas import Intent, IntentResult
from apps.core.enums import ItemKind
from apps.core.registry import model_for_kind

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

OFFSET_VALUES = {value for value, _ in REMINDER_OFFSETS if value != ""}


def _initial_from_target(draft) -> dict:
    """Valorile curente ale obiectului vizat de o comanda de modificare.

    Returneaza `{}` daca tinta nu poate fi identificata — atunci formularul
    ramane pe schita, ca inainte.
    """
    kind = draft.target_kind or None
    pk = draft.target_id
    if not kind or not pk:
        return {}
    model = model_for_kind(kind)
    if model is None:
        return {}
    obj = model.objects.filter(pk=pk, owner=draft.owner).first()
    if obj is None:
        return {}

    if kind == ItemKind.NOTE:
        return {"title": obj.title, "description": obj.content}

    if kind == ItemKind.APPOINTMENT:
        starts = timezone.localtime(obj.starts_at)
        return {
            "title": obj.title,
            "description": obj.description,
            "location": obj.location,
            "date": starts.date(),
            "start_time": starts.time().replace(second=0, microsecond=0),
            "end_time": (
                timezone.localtime(obj.ends_at).time().replace(second=0, microsecond=0)
                if obj.ends_at
                else None
            ),
        }

    if kind == ItemKind.REMINDER:
        remind = timezone.localtime(obj.remind_at)
        return {
            "title": obj.title,
            "description": obj.description,
            "date": remind.date(),
            "start_time": remind.time().replace(second=0, microsecond=0),
            # Un decalaj personalizat nu are optiune in lista; il lasam gol, ca
            # `TypedChoiceField` sa nu respinga formularul la trimitere.
            "reminder_offset": (
                obj.offset_minutes
                if obj.appointment_id and obj.offset_minutes in OFFSET_VALUES
                else None
            ),
        }

    return {}


class DraftForm(forms.Form):
    """Campurile vin din schita; utilizatorul le poate schimba pe toate."""

    intent = forms.ChoiceField(label="Tip", choices=INTENT_CHOICES)
    title = forms.CharField(label="Titlu", max_length=200)
    description = forms.CharField(
        label="Detalii", required=False, widget=forms.Textarea(attrs={"rows": 3})
    )
    date = forms.DateField(
        label="Dată",
        required=False,
        # `<input type="date">` citeste `value` doar in format ISO. Fara `format`,
        # Django randeaza data localizat („05.09.2026") si browserul ignora
        # valoarea: campul apare gol, desi data a fost interpretata corect.
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
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
            # La modificare pornim de la obiectul existent, nu de la schita.
            # Comanda spune doar ce se schimba („mută la ora 14"), deci restul
            # campurilor trebuie sa arate valorile reale; altfel utilizatorul ar
            # trimite inapoi campuri goale si ar sterge datele pe care nu le-a
            # atins. Peste ele punem doar ce a rostit efectiv.
            base = _initial_from_target(draft) if draft.intent == Intent.UPDATE_ITEM else {}
            spoken = {
                "title": result.title,
                "description": result.description,
                "date": result.date,
                "start_time": result.start_time,
                "end_time": result.end_time,
                "location": result.location,
                "person": result.person,
                "reminder_offset": result.reminder_offset,
            }
            if not base:
                # Creare: titlul lipsa se completeaza cu textul rostit, ca
                # utilizatorul sa aiba de unde porni.
                spoken["title"] = result.title or draft.source_text[:200]
            self.initial.update(
                {
                    "intent": result.intent,
                    **base,
                    **{key: value for key, value in spoken.items() if value is not None},
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
