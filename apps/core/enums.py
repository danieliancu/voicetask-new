"""Enumerari partajate intre aplicatii."""

from django.db import models


class Source(models.TextChoices):
    """Cum a ajuns un obiect in aplicatie."""

    MANUAL = "manual", "Introdus manual"
    VOICE = "voice", "Comanda vocala"
    SCAN = "scan", "Document scanat"
    EMAIL = "email", "Email"
    CALENDAR = "calendar", "Google Calendar"


class ColorToken(models.TextChoices):
    """Tokenul de culoare pentru tabul lateral al cardului."""

    VIOLET = "violet", "Violet"
    BLUE = "blue", "Albastru"
    MINT = "mint", "Verde mentă"
    ORANGE = "orange", "Portocaliu"


class ItemKind(models.TextChoices):
    """Tipurile de obiecte pe care utilizatorul le poate crea, edita sau sterge."""

    NOTE = "notita", "Notiță"
    APPOINTMENT = "programare", "Programare"
    REMINDER = "alarma", "Alarmă"
    DOCUMENT = "document", "Document"
    EMAIL = "email", "Email"
