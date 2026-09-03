"""Google Calendar demonstrativ.

Evenimentele externe se pastreaza intr-un dictionar in memorie per proces, ca
fluxul de creare / modificare / stergere sa fie complet parcurgibil. Crearea
returneaza un identificator stabil derivat din programarea locala, deci o a doua
sincronizare a aceleiasi programari nu produce un eveniment duplicat.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from django.utils import timezone

from apps.core.providers.base import CalendarProvider, ExternalEvent

_STORE: dict[str, ExternalEvent] = {}


def _external_id(appointment) -> str:
    return f"demo-cal-{appointment.owner_id}-{appointment.pk}"


class MockCalendarProvider(CalendarProvider):
    name = "calendar-demo"
    is_mock = True

    def list_events(self, account, *, start: datetime, end: datetime) -> list[ExternalEvent]:
        now = timezone.now()
        maine = now + timedelta(days=1)
        seeded = [
            ExternalEvent(
                external_id="demo-cal-seed-alpha",
                title="Întâlnire proiect Alpha",
                starts_at=maine.replace(hour=10, minute=0, second=0, microsecond=0),
                ends_at=maine.replace(hour=11, minute=0, second=0, microsecond=0),
                location="Google Meet",
                description="Sincronizat din Google Calendar (demonstrativ).",
                updated_at=now,
            )
        ]
        events = seeded + list(_STORE.values())
        return [event for event in events if start <= event.starts_at <= end]

    def create_event(self, account, *, appointment) -> ExternalEvent:
        event = ExternalEvent(
            external_id=_external_id(appointment),
            title=appointment.title,
            starts_at=appointment.starts_at,
            ends_at=appointment.ends_at,
            location=appointment.location,
            description=appointment.description,
            updated_at=timezone.now(),
        )
        _STORE[event.external_id] = event
        return event

    def update_event(self, account, *, appointment) -> ExternalEvent:
        return self.create_event(account, appointment=appointment)

    def delete_event(self, account, *, external_id: str) -> None:
        _STORE.pop(external_id, None)


def reset_store() -> None:
    """Folosit de teste pentru a porni de la o stare curata."""
    _STORE.clear()
