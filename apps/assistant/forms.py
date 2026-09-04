"""Formularele schitei: ultimul pas editabil inainte de salvare.

Un singur formular universal arata aceleasi campuri pentru toate tipurile, deci o
notita primea data, ora, locatie, persoana si alarma — campuri care nu au unde sa
se salveze — iar un dropdown de tip putea transforma din greseala notita in
programare. Fiecare intentie are acum formularul ei, ales pe server dupa schita.
Tipul se vede in antetul schitei; nu mai este ceva de ales din formular.
"""

from __future__ import annotations

from django import forms
from django.utils import timezone

from apps.accounts.models import UserPreference
from apps.assistant.schemas import Intent, IntentResult
from apps.core.enums import ItemKind
from apps.core.registry import model_for_kind

REMINDER_OFFSETS = (
    ("", "Fără alarmă"),
    (0, "La momentul evenimentului"),
    (10, "Cu 10 minute înainte"),
    (30, "Cu 30 de minute înainte"),
    (60, "Cu o oră înainte"),
    (1440, "Cu o zi înainte"),
)

OFFSET_VALUES = {value for value, _ in REMINDER_OFFSETS if value != ""}

#: `<input type="date">` citeste `value` doar in format ISO. Fara `format`, Django
#: randeaza data localizat („05.09.2026") si browserul ignora valoarea: campul apare
#: gol, desi data a fost interpretata corect.
DATE_WIDGET = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


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
        return {
            "title": obj.title,
            "description": obj.content,
            "category_id": obj.category_id,
            "is_pinned": obj.is_pinned,
        }

    tz = UserPreference.for_user(draft.owner).tzinfo
    if kind == ItemKind.APPOINTMENT:
        starts = timezone.localtime(obj.starts_at, tz)
        return {
            "title": obj.title,
            "description": obj.description,
            "location": obj.location,
            "date": starts.date(),
            "start_time": None if obj.all_day else starts.time().replace(second=0, microsecond=0),
            "all_day": obj.all_day,
            "end_time": (
                timezone.localtime(obj.ends_at, tz).time().replace(second=0, microsecond=0)
                if obj.ends_at and not obj.all_day
                else None
            ),
        }

    if kind == ItemKind.REMINDER:
        remind = timezone.localtime(obj.remind_at, tz)
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


class BaseDraftForm(forms.Form):
    """Ce au in comun toate formularele de schita.

    Intentia nu este un camp: o declara clasa. Asa nu se poate schimba tipul din
    formular, iar `to_overrides` stie mereu ce salveaza.
    """

    #: Intentia pe care o serveste formularul. Fiecare subclasa o declara.
    intent: Intent = Intent.UNKNOWN

    #: Campurile trimise mai departe catre schema, in afara de `intent`.
    override_fields: tuple[str, ...] = ()

    title = forms.CharField(label="Titlu", max_length=200)

    def __init__(self, *args, draft=None, **kwargs):
        self.draft = draft
        super().__init__(*args, **kwargs)
        if draft is not None:
            self.prepare(draft)
        if draft is not None and not self.is_bound:
            self.initial.update(self.initial_values(draft))

    def prepare(self, draft) -> None:
        """Ajusteaza campurile in functie de schita. Implicit, nimic."""

    def initial_values(self, draft) -> dict:
        result = IntentResult.model_validate(draft.payload)
        # La modificare pornim de la obiectul existent, nu de la schita. Comanda
        # spune doar ce se schimba („mută la ora 14"), deci restul campurilor
        # trebuie sa arate valorile reale; altfel utilizatorul ar trimite inapoi
        # campuri goale si ar sterge datele pe care nu le-a atins.
        base = _initial_from_target(draft) if draft.intent == Intent.UPDATE_ITEM else {}
        spoken = {name: getattr(result, name, None) for name in self.override_fields}
        if not base:
            # Creare: titlul lipsa se completeaza cu textul rostit, ca utilizatorul
            # sa aiba de unde porni.
            spoken["title"] = result.title or draft.source_text[:200]
        return {**base, **{key: value for key, value in spoken.items() if value is not None}}

    def intent_for_save(self) -> Intent:
        """Ce tip se salveaza.

        La modificare, formularul este ales dupa tipul obiectului vizat, dar
        intentia ramane „modificare": altfel „mută programarea la 16" ar crea o
        programare noua in loc sa o mute pe cea existenta.
        """
        if self.draft is not None and self.draft.intent in {
            Intent.UPDATE_ITEM,
            Intent.DELETE_ITEM,
        }:
            return self.draft.intent
        return self.intent

    def to_overrides(self) -> dict:
        """Valorile editate, in formatul asteptat de schema."""
        data = self.cleaned_data
        overrides: dict = {"intent": self.intent_for_save()}
        for name in self.override_fields:
            value = data.get(name)
            if hasattr(value, "isoformat"):
                value = value.isoformat()
            elif isinstance(value, str):
                value = value or None
            overrides[name] = value
        return overrides


class NoteDraftForm(BaseDraftForm):
    """Notita nu are dată, oră, locație, persoană sau alarmă. Deci nu le arata."""

    intent = Intent.CREATE_NOTE
    override_fields = ("title", "description", "category_id", "is_pinned")

    description = forms.CharField(
        label="Conținut", required=False, widget=forms.Textarea(attrs={"rows": 6})
    )
    category_id = forms.ChoiceField(label="Categorie", required=False)
    is_pinned = forms.BooleanField(label="Fixează notița", required=False)

    def prepare(self, draft) -> None:
        from apps.notes.models import NoteCategory

        # Lista se construieste din categoriile utilizatorului, deci `ChoiceField`
        # respinge singur un id venit din alt cont: nu ajunge niciodata la salvare.
        categorii = NoteCategory.objects.filter(owner=draft.owner).order_by("name")
        self.fields["category_id"].choices = [("", "Fără categorie")] + [
            (str(category.pk), category.name) for category in categorii
        ]

    def clean_category_id(self):
        value = self.cleaned_data.get("category_id")
        return int(value) if value else None

    def clean(self):
        data = super().clean()
        if not data.get("title") and not data.get("description"):
            self.add_error("title", "Scrie un titlu sau un conținut.")
        return data


class AppointmentDraftForm(BaseDraftForm):
    """Programarea are nevoie de zi si de ora; „Toată ziua" este singura scutire."""

    intent = Intent.CREATE_APPOINTMENT
    override_fields = (
        "title",
        "description",
        "date",
        "start_time",
        "end_time",
        "all_day",
        "location",
        "person",
        "reminder_offset",
    )

    description = forms.CharField(
        label="Detalii", required=False, widget=forms.Textarea(attrs={"rows": 3})
    )
    date = forms.DateField(label="Dată", required=False, widget=DATE_WIDGET)
    start_time = forms.TimeField(
        label="Ora de început", required=False, widget=forms.TimeInput(attrs={"type": "time"})
    )
    end_time = forms.TimeField(
        label="Ora de final", required=False, widget=forms.TimeInput(attrs={"type": "time"})
    )
    all_day = forms.BooleanField(label="Toată ziua", required=False)
    location = forms.CharField(label="Locație", required=False, max_length=200)
    person = forms.CharField(label="Persoană", required=False, max_length=120)
    reminder_offset = forms.TypedChoiceField(
        label="Alarmă", choices=REMINDER_OFFSETS, coerce=int, required=False, empty_value=None
    )

    def clean(self):
        """Ultima verificare inainte de salvare.

        Butonul dezactivat si politica de clarificare tin de interfata; aici se
        decide efectiv. O programare fara ora nu trece, oricat de completa ar parea
        schita — singura exceptie este „toată ziua", cerut explicit de utilizator.
        """
        data = super().clean()
        all_day = data.get("all_day")
        start, end = data.get("start_time"), data.get("end_time")

        if not data.get("date"):
            self.add_error("date", "Alege o dată.")
        if not start and not all_day:
            self.add_error("start_time", "Alege o oră.")
        if all_day and (start or end):
            self.add_error("all_day", "O programare pe toată ziua nu are oră.")
        if start and end and end < start:
            self.add_error("end_time", "Ora de final nu poate fi înaintea celei de început.")
        return data


class ReminderDraftForm(BaseDraftForm):
    """Alarma suna la un moment anume: titlu, zi, ora. Nimic altceva."""

    intent = Intent.CREATE_REMINDER
    override_fields = ("title", "description", "date", "start_time")

    description = forms.CharField(
        label="Detalii", required=False, widget=forms.Textarea(attrs={"rows": 3})
    )
    date = forms.DateField(label="Dată", required=False, widget=DATE_WIDGET)
    start_time = forms.TimeField(
        label="Oră", required=False, widget=forms.TimeInput(attrs={"type": "time"})
    )

    def clean(self):
        data = super().clean()
        if not data.get("date"):
            self.add_error("date", "Alege o dată.")
        if not data.get("start_time"):
            self.add_error("start_time", "Alege o oră.")
        return data


class EmailFollowUpForm(BaseDraftForm):
    """Marcheaza un email existent pentru urmarire. Nu trimite nimic.

    Emailul se alege dintre cele ale utilizatorului: querysetul campului este si
    verificarea de proprietate, deci un id din alt cont nu trece de validare.
    """

    intent = Intent.FOLLOW_UP_EMAIL
    override_fields = ("title", "description", "date", "start_time", "target_id")

    title = forms.CharField(label="Titlu", max_length=200, required=False)
    target_id = forms.ModelChoiceField(
        label="Emailul de urmărit",
        queryset=None,
        empty_label=None,
        widget=forms.RadioSelect,
    )
    date = forms.DateField(label="Dată", required=False, widget=DATE_WIDGET)
    start_time = forms.TimeField(
        label="Oră", required=False, widget=forms.TimeInput(attrs={"type": "time"})
    )
    description = forms.CharField(
        label="Notă", required=False, widget=forms.Textarea(attrs={"rows": 3})
    )

    #: Cate emailuri se ofera spre alegere cand comanda nu a potrivit niciunul.
    RECENT_LIMIT = 20

    def prepare(self, draft) -> None:
        from apps.integrations.models import EmailReference

        toate = EmailReference.objects.for_user(draft.owner)
        # Lista se restrange la potrivirile gasite pentru comanda rostita; fara ele,
        # la cele mai recente. In ambele cazuri sunt doar emailurile utilizatorului,
        # deci validarea campului este si verificarea de proprietate.
        pks = [
            candidate.get("pk")
            for candidate in (draft.candidates or [])
            if candidate.get("kind") == ItemKind.EMAIL
        ]
        if draft.target_id:
            pks.append(draft.target_id)
        if not pks:
            recente = toate.order_by("-received_at").values_list("pk", flat=True)
            pks = list(recente[: self.RECENT_LIMIT])
        self.fields["target_id"].queryset = toate.filter(pk__in=pks).order_by("-received_at")
        self.fields["target_id"].label_from_instance = _email_label
        # Titlul nu este cerut: emailul isi are subiectul lui.
        self.fields["title"].required = False

    def initial_values(self, draft) -> dict:
        values = super().initial_values(draft)
        if draft.target_id:
            values["target_id"] = draft.target_id
        values.pop("title", None)
        return values

    @property
    def selected_email(self):
        """Emailul ales, pentru afisarea expeditorului si subiectului."""
        field = self.fields["target_id"]
        raw = self.data.get(self.add_prefix("target_id")) if self.is_bound else None
        value = raw or self.initial.get("target_id")
        if not value:
            return None
        return field.queryset.filter(pk=value).first()

    def clean(self):
        data = super().clean()
        if not data.get("date"):
            self.add_error("date", "Alege o dată.")
        if not data.get("start_time"):
            self.add_error("start_time", "Alege o oră.")
        return data

    def to_overrides(self) -> dict:
        overrides = super().to_overrides()
        email = self.cleaned_data.get("target_id")
        overrides["target_id"] = email.pk if email else None
        overrides["target_kind"] = ItemKind.EMAIL if email else None
        # Titlul schitei ramane subiectul emailului, ca lista sa fie de recunoscut.
        overrides["title"] = (email.subject or email.sender_name)[:200] if email else None
        return overrides


def _email_label(email) -> str:
    """Eticheta din lista de alegere: cine a scris si despre ce."""
    return f"{email.sender_name} — {email.subject or 'fără subiect'}"


#: Ce formular serveste fiecare intentie. Pentru modificare conteaza tipul obiectului
#: vizat, nu intentia: „mută programarea" editeaza o programare.
FORMS_BY_INTENT = {
    Intent.CREATE_NOTE: NoteDraftForm,
    Intent.CREATE_APPOINTMENT: AppointmentDraftForm,
    Intent.CREATE_REMINDER: ReminderDraftForm,
    Intent.FOLLOW_UP_EMAIL: EmailFollowUpForm,
}

FORMS_BY_KIND = {
    ItemKind.NOTE: NoteDraftForm,
    ItemKind.APPOINTMENT: AppointmentDraftForm,
    ItemKind.REMINDER: ReminderDraftForm,
    ItemKind.EMAIL: EmailFollowUpForm,
}


def get_draft_form_class(draft) -> type[BaseDraftForm] | None:
    """Formularul potrivit schitei, sau `None` daca nu are ce fi editat.

    O cautare si o comanda neinteleasa nu se salveaza, deci nu au formular; o
    stergere se confirma, nu se editeaza.
    """
    if draft.intent == Intent.UPDATE_ITEM:
        return FORMS_BY_KIND.get(draft.target_kind, AppointmentDraftForm)
    return FORMS_BY_INTENT.get(draft.intent)


class TextCommandForm(forms.Form):
    """Alternativa scrisa, pentru cand microfonul nu este disponibil.

    Cand tipul ales este „Notă", textul nu este o comanda, ci chiar notita — deci
    eticheta nu mai promite interpretare.
    """

    text = forms.CharField(
        label="Scrie comanda",
        max_length=500,
        widget=forms.Textarea(
            attrs={"rows": 3, "placeholder": "Ex.: Programare mâine la 10 cu Ana"}
        ),
    )
    mode = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, intent: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.intent = intent
        if intent == Intent.CREATE_NOTE:
            self.fields["text"].label = "Scrie notița"
            self.fields["text"].widget.attrs["placeholder"] = "Ex.: De cumpărat: lapte, pâine"
            self.fields["text"].widget.attrs["rows"] = 6
