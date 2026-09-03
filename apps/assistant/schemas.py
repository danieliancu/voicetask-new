"""Schema stricta a rezultatului interpretarii unei comenzi.

Orice provider (AI sau bazat pe reguli) trebuie sa producă exact aceasta structura.
`extra="forbid"` inseamna ca un camp inventat de model face validarea sa esueze —
preferam o eroare vizibila unei salvari gresite.
"""

from __future__ import annotations

# Aliasuri: campul `date` din schema ar umbri tipul `datetime.date`.
from datetime import date as date_type
from datetime import time as time_type
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class Intent(StrEnum):
    CREATE_NOTE = "create_note"
    CREATE_APPOINTMENT = "create_appointment"
    CREATE_REMINDER = "create_reminder"
    FOLLOW_UP_EMAIL = "follow_up_email"
    UPDATE_ITEM = "update_item"
    DELETE_ITEM = "delete_item"
    SEARCH = "search"
    UNKNOWN = "unknown"


#: Intentiile care modifica sau sterg date existente cer intotdeauna confirmare.
DESTRUCTIVE_INTENTS = frozenset({Intent.DELETE_ITEM})
MUTATING_INTENTS = frozenset({Intent.UPDATE_ITEM, Intent.DELETE_ITEM})

INTENT_LABELS = {
    Intent.CREATE_NOTE: "Notă",
    Intent.CREATE_APPOINTMENT: "Programare",
    Intent.CREATE_REMINDER: "Alarmă",
    Intent.FOLLOW_UP_EMAIL: "Email",
    Intent.UPDATE_ITEM: "Modificare",
    Intent.DELETE_ITEM: "Ștergere",
    Intent.SEARCH: "Căutare",
    Intent.UNKNOWN: "Nedeterminat",
}


class IntentResult(BaseModel):
    """Rezultatul validat. Nimic din afara acestor campuri nu ajunge in aplicatie."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    intent: Intent = Intent.UNKNOWN
    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    date: date_type | None = None
    start_time: time_type | None = None
    end_time: time_type | None = None
    location: str | None = Field(default=None, max_length=200)
    reminder_offset: int | None = Field(default=None, ge=0, le=10080)
    search_query: str | None = Field(default=None, max_length=200)
    target_id: int | None = Field(default=None, ge=1)
    target_kind: str | None = Field(default=None, max_length=20)
    person: str | None = Field(default=None, max_length=120)
    amount: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=8)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    clarification_required: bool = False
    clarification_question: str | None = Field(default=None, max_length=300)
    #: Motivul pentru care interpretarea este incerta; folosit de politica de decizie.
    ambiguity: list[str] = Field(default_factory=list)

    @field_validator("title", "description", "location", "search_query", "person", mode="before")
    @classmethod
    def blank_to_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def check_coherence(self) -> IntentResult:
        if self.end_time and self.start_time and self.end_time < self.start_time:
            raise ValueError("Ora de final nu poate fi înaintea orei de început.")
        if self.intent == Intent.SEARCH and not self.search_query:
            raise ValueError("Intenția de căutare are nevoie de un termen.")
        if self.clarification_required and not self.clarification_question:
            raise ValueError("Clarificarea are nevoie de o întrebare.")
        return self

    @property
    def needs_target(self) -> bool:
        return self.intent in MUTATING_INTENTS

    @property
    def is_destructive(self) -> bool:
        return self.intent in DESTRUCTIVE_INTENTS

    @property
    def label(self) -> str:
        return INTENT_LABELS.get(self.intent, "Nedeterminat")


def parse_result(raw: dict[str, Any]) -> IntentResult:
    """Valideaza un dict brut. Ridica `IntentValidationError` la orice abatere."""
    try:
        return IntentResult.model_validate(raw)
    except ValidationError as exc:
        raise IntentValidationError(exc) from exc


class IntentValidationError(Exception):
    """Providerul a returnat ceva ce nu respecta schema."""

    user_message = "Nu am putut interpreta comanda. Încearcă să o reformulezi."

    def __init__(self, original: ValidationError):
        self.original = original
        super().__init__(str(original))

    @property
    def fields(self) -> list[str]:
        return [".".join(str(part) for part in err["loc"]) for err in self.original.errors()]


#: Schema JSON transmisa modelului AI, ca sa raspunda direct in formatul corect.
JSON_SCHEMA = IntentResult.model_json_schema()
