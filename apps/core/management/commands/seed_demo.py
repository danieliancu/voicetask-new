"""Populeaza aplicatia cu datele din mockup-uri.

Toate datele sunt relative fata de momentul rularii, deci demo-ul ramane
relevant oricand. Comanda este idempotenta: rulata de doua ori nu dubleaza nimic.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import UserPreference
from apps.core.enums import ColorToken, Source
from apps.documents.models import ScannedDocument
from apps.integrations.models import ConnectedAccount
from apps.integrations.sync import sync_calendar, sync_emails
from apps.notes.models import ChecklistItem, Note, NoteCategory
from apps.scheduling.models import Appointment, Reminder
from apps.scheduling.services import sync_appointment_reminder

User = get_user_model()

CATEGORIES = (
    ("Personale", "personale", ColorToken.VIOLET, "users", 0),
    ("Muncă", "munca", ColorToken.BLUE, "file", 1),
    ("Idei", "idei", ColorToken.ORANGE, "lightbulb", 2),
    ("Documente", "documente", ColorToken.MINT, "scan", 3),
)


def at(day_offset: int, hour: int, minute: int = 0) -> datetime:
    """Un moment relativ la ziua de azi, in ora locala."""
    day = timezone.localdate() + timedelta(days=day_offset)
    return timezone.make_aware(
        datetime.combine(day, time(hour, minute)), timezone.get_current_timezone()
    )


class Command(BaseCommand):
    help = "Creează un utilizator demonstrativ și datele din mockup-uri."

    def add_arguments(self, parser):
        parser.add_argument("--user", default="demo", help="Numele utilizatorului (implicit: demo)")
        parser.add_argument("--password", default="demo1234", help="Parola utilizatorului")
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Șterge definitiv datele existente ale acestui utilizator",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        username = options["user"]
        user, created = User.objects.get_or_create(
            username=username, defaults={"email": f"{username}@example.com"}
        )
        if created or options["password"]:
            user.set_password(options["password"])
            user.save()

        prefs = UserPreference.for_user(user)
        prefs.display_name = "Daniel"
        prefs.save()

        if options["reset"]:
            self._reset(user)

        categories = self._categories(user)
        appointments = self._appointments(user)
        self._reminders(user, appointments)
        self._notes(user, categories)
        self._documents(user)
        self._integrations(user)

        password = options["password"]
        self.stdout.write(
            self.style.SUCCESS(
                f"Date demonstrative create pentru utilizatorul {username} (parolă: {password})."
            )
        )
        self.stdout.write("Deschide http://127.0.0.1:8000/ și autentifică-te.")

    # ------------------------------------------------------------------ pasi

    def _reset(self, user) -> None:
        for model in (Reminder, Appointment, Note, NoteCategory, ScannedDocument):
            model.all_objects.filter(owner=user).hard_delete()
        from apps.integrations.models import EmailReference

        EmailReference.all_objects.filter(owner=user).hard_delete()

    def _categories(self, user) -> dict[str, NoteCategory]:
        result = {}
        for name, slug, color, icon, position in CATEGORIES:
            category, _ = NoteCategory.all_objects.update_or_create(
                owner=user,
                slug=slug,
                defaults={"name": name, "color": color, "icon": icon, "position": position},
            )
            result[slug] = category
        return result

    def _appointments(self, user) -> dict[str, Appointment]:
        data = (
            (
                "alpha",
                {
                    "title": "Întâlnire proiect Alpha",
                    "description": "Sincronizare săptămânală cu echipa.",
                    "location": "Google Meet",
                    "starts_at": at(1, 10, 0),
                    "ends_at": at(1, 11, 0),
                    "color": ColorToken.VIOLET,
                    "icon": "calendar",
                },
                30,
            ),
            (
                "medical",
                {
                    "title": "Control medical",
                    "description": "Consultație de rutină.",
                    "location": "Clinica MedLife",
                    "starts_at": at(3, 9, 0),
                    "ends_at": at(3, 10, 0),
                    "color": ColorToken.MINT,
                    "icon": "stethoscope",
                },
                60,
            ),
            (
                "parinti",
                {
                    "title": "Ședință cu părinții",
                    "description": "Sala festivă, etajul 1.",
                    "location": "Școala Nr. 12",
                    "starts_at": at(6, 17, 30),
                    "ends_at": at(6, 18, 30),
                    "color": ColorToken.ORANGE,
                    "icon": "users",
                },
                60,
            ),
            (
                "zbor",
                {
                    "title": "Zbor: București – Cluj-Napoca",
                    "description": "Îmbarcare cu 40 de minute înainte.",
                    "location": "Aeroport Otopeni",
                    "starts_at": at(9, 7, 15),
                    "ends_at": at(9, 8, 30),
                    "color": ColorToken.BLUE,
                    "icon": "plane",
                },
                60,
            ),
        )
        appointments = {}
        for key, fields, offset in data:
            appointment, _ = Appointment.all_objects.update_or_create(
                owner=user, title=fields["title"], defaults={**fields, "source": Source.MANUAL}
            )
            sync_appointment_reminder(appointment, offset)
            appointments[key] = appointment
        return appointments

    def _reminders(self, user, appointments) -> None:
        Reminder.all_objects.update_or_create(
            owner=user,
            title="Plătește factura la internet",
            defaults={
                "description": "Orice rețea, plată online.",
                "remind_at": at(10, 12, 0),
                "source": Source.MANUAL,
            },
        )

    def _notes(self, user, categories) -> None:
        checklist, _ = Note.all_objects.update_or_create(
            owner=user,
            title="Checklist vacanță",
            defaults={
                "content": "Pașaport, asigurare, bilete, rezervări, încărcătoare, adaptoare.",
                "category": categories["personale"],
                "source": Source.MANUAL,
            },
        )
        items = ["Pașaport", "Asigurare", "Bilete", "Rezervări", "Încărcătoare", "Adaptoare"]
        for position, text in enumerate(items):
            ChecklistItem.all_objects.update_or_create(
                note=checklist, text=text, defaults={"position": position}
            )

        cumparaturi, _ = Note.all_objects.update_or_create(
            owner=user,
            title="Lista cumpărături",
            defaults={
                "content": "Lapte, ouă, pâine integrală, fructe, legume, cafea.",
                "category": categories["personale"],
                "source": Source.VOICE,
            },
        )
        for position, text in enumerate(
            ["Lapte", "Ouă", "Pâine integrală", "Fructe", "Legume", "Cafea"]
        ):
            ChecklistItem.all_objects.update_or_create(
                note=cumparaturi, text=text, defaults={"position": position}
            )

        Note.all_objects.update_or_create(
            owner=user,
            title="Brief întâlnire Alpha",
            defaults={
                "content": "Obiective, participanți, agendă, materiale necesare.",
                "category": categories["munca"],
                "source": Source.MANUAL,
            },
        )
        Note.all_objects.update_or_create(
            owner=user,
            title="Idei pentru campanie de vară",
            defaults={
                "content": (
                    "• Copy pentru social media\n"
                    "• Concept vizual – moodboard\n"
                    "• Buget estimativ"
                ),
                "category": categories["idei"],
                "source": Source.MANUAL,
            },
        )

    def _documents(self, user) -> None:
        due = timezone.localdate() + timedelta(days=3)
        factura, _ = ScannedDocument.all_objects.update_or_create(
            owner=user,
            title="Factura energie",
            defaults={
                "document_type": ScannedDocument.DocumentType.INVOICE,
                "processing_status": ScannedDocument.Status.CONFIRMED,
                "ocr_confidence": 0.88,
                "ocr_provider": "demo",
                "extracted_text": (
                    "FACTURA ENERGIE ELECTRICA\n"
                    "TOTAL DE PLATA 84,20 lei\n"
                    f"DATA LIMITA DE PLATA {due:%d.%m.%Y}"
                ),
                "extracted_data": {
                    "due_date": {
                        "value": due.isoformat(),
                        "confidence": 0.91,
                        "evidence": "DATA LIMITA DE PLATA",
                    },
                    "amount": {
                        "value": 84.2,
                        "confidence": 0.87,
                        "evidence": "TOTAL DE PLATA 84,20 lei",
                    },
                    "currency": {"value": "lei", "confidence": 0.87, "evidence": ""},
                    "document_type": {"value": "invoice", "confidence": 0.9, "evidence": ""},
                    "title": {"value": "Factura energie", "confidence": 0.8, "evidence": ""},
                    "suggested_action": {"value": "reminder", "confidence": 0.5, "evidence": ""},
                },
                "confirmed_at": timezone.now(),
            },
        )
        Note.all_objects.update_or_create(
            owner=user,
            title="Factura energie",
            defaults={
                "content": "Sumă: 84.20 lei\nPlata prin debit direct.",
                "source": Source.SCAN,
                "source_document": factura,
                "is_pinned": True,
            },
        )
        Reminder.all_objects.update_or_create(
            owner=user,
            title="Factura energie",
            defaults={
                "description": "Termen de plată.",
                "remind_at": at(2, 9, 0),
                "offset_minutes": 1440,
                "document": factura,
                "source": Source.SCAN,
            },
        )

        event_date = timezone.localdate() + timedelta(days=11)
        invitatie, _ = ScannedDocument.all_objects.update_or_create(
            owner=user,
            title="Invitație serbare",
            defaults={
                "document_type": ScannedDocument.DocumentType.INVITATION,
                "processing_status": ScannedDocument.Status.READY,
                "ocr_confidence": 0.79,
                "ocr_provider": "demo",
                "extracted_text": (
                    "INVITATIE\nVa invitam la serbarea scolara de sfarsit de an\n"
                    f"Scoala Nr. 12, Sala festiva\n{event_date:%d.%m.%Y}, ora 10:00"
                ),
                "extracted_data": {
                    "event_date": {
                        "value": event_date.isoformat(),
                        "confidence": 0.72,
                        "evidence": "Va invitam",
                    },
                    "time": {"value": "10:00", "confidence": 0.66, "evidence": "ora 10:00"},
                    "location": {"value": "Școala Nr. 12", "confidence": 0.6, "evidence": ""},
                    "document_type": {"value": "invitation", "confidence": 0.85, "evidence": ""},
                    "title": {"value": "Invitație serbare", "confidence": 0.7, "evidence": ""},
                    "suggested_action": {"value": "appointment", "confidence": 0.5, "evidence": ""},
                },
            },
        )
        Note.all_objects.update_or_create(
            owner=user,
            title="Invitație serbare",
            defaults={
                "content": "Text recunoscut (OCR): „Vă invităm la serbarea școlară…”",
                "source": Source.SCAN,
                "source_document": invitatie,
            },
        )

    def _integrations(self, user) -> None:
        """Activeaza providerii demonstrativi si importa emailurile de exemplu."""
        for provider in (ConnectedAccount.Provider.GMAIL, ConnectedAccount.Provider.CALENDAR):
            ConnectedAccount.objects.update_or_create(
                owner=user,
                provider=provider,
                defaults={
                    "status": ConnectedAccount.Status.MOCK,
                    "email": "demo@example.com",
                    "external_account_id": f"demo-{provider}",
                },
            )
        sync_emails(user)
        sync_calendar(user)

        from apps.integrations.models import EmailReference

        ana = EmailReference.objects.for_user(user).filter(sender__icontains="Ana Popescu").first()
        if ana is not None:
            ana.status = EmailReference.Status.FOLLOW_UP
            ana.follow_up_at = at(1, 14, 0)
            ana.save(update_fields=["status", "follow_up_at", "updated_at"])
