"""Fixtures comune. Toate testele ruleaza pe provideri mock, fara retea."""

from __future__ import annotations

import io
import socket
import wave
from datetime import datetime, time, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.accounts.models import UserPreference
from apps.core.enums import Source


@pytest.fixture(scope="session", autouse=True)
def block_network():
    """Orice apel de retea dintr-un test trebuie sa esueze zgomotos."""
    allowed = socket.socket

    class BlockedSocket(allowed):
        def connect(self, address):
            host = address[0] if isinstance(address, tuple) else ""
            if host in {"127.0.0.1", "::1", "localhost"}:
                return super().connect(address)
            raise RuntimeError(f"Testele nu au voie sa acceseze reteaua ({address}).")

    socket.socket = BlockedSocket
    yield
    socket.socket = allowed


@pytest.fixture(autouse=True)
def clear_providers():
    """Cache-ul de provideri nu trebuie sa treaca de la un test la altul."""
    from apps.core.providers.registry import clear_provider_cache

    clear_provider_cache()
    yield
    clear_provider_cache()


@pytest.fixture
def make_user(db):
    User = get_user_model()
    counter = {"n": 0}

    def factory(username: str | None = None, password: str = "parola-test-123"):
        counter["n"] += 1
        name = username or f"user{counter['n']}"
        user = User.objects.create_user(username=name, password=password)
        UserPreference.for_user(user)
        return user

    return factory


@pytest.fixture
def user(make_user):
    return make_user("demo")


@pytest.fixture
def other_user(make_user):
    return make_user("altcineva")


@pytest.fixture
def prefs(user):
    return UserPreference.for_user(user)


@pytest.fixture
def auth_client(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def other_client(client, other_user):
    from django.test import Client

    other = Client()
    other.force_login(other_user)
    return other


@pytest.fixture
def at():
    """Un moment relativ la ziua curenta, in ora locala."""

    def factory(day_offset: int = 0, hour: int = 10, minute: int = 0):
        day = timezone.localdate() + timedelta(days=day_offset)
        return timezone.make_aware(
            datetime.combine(day, time(hour, minute)), timezone.get_current_timezone()
        )

    return factory


@pytest.fixture
def note_factory(db):
    from apps.notes.models import Note

    def factory(owner, title="Notiță de test", **kwargs):
        return Note.objects.create(owner=owner, title=title, **kwargs)

    return factory


@pytest.fixture
def appointment_factory(db, at):
    from apps.scheduling.models import Appointment

    def factory(owner, title="Programare de test", day_offset=1, hour=10, **kwargs):
        starts = kwargs.pop("starts_at", at(day_offset, hour))
        return Appointment.objects.create(
            owner=owner,
            title=title,
            starts_at=starts,
            ends_at=kwargs.pop("ends_at", starts + timedelta(hours=1)),
            **kwargs,
        )

    return factory


@pytest.fixture
def reminder_factory(db, at):
    from apps.scheduling.models import Reminder

    def factory(owner, title="Alarmă de test", day_offset=1, hour=9, **kwargs):
        return Reminder.objects.create(
            owner=owner,
            title=title,
            remind_at=kwargs.pop("remind_at", at(day_offset, hour)),
            **kwargs,
        )

    return factory


@pytest.fixture
def document_factory(db):
    from django.core.files.base import ContentFile

    from apps.documents.models import ScannedDocument

    def factory(owner, title="Document de test", **kwargs):
        document = ScannedDocument(owner=owner, title=title, **kwargs)
        document.original_image.save("test.jpg", ContentFile(sample_jpeg()), save=False)
        document.save()
        return document

    return factory


@pytest.fixture
def email_factory(db):
    from apps.integrations.models import EmailReference

    def factory(owner, subject="Subiect de test", sender="Ana Popescu <ana@example.com>", **kwargs):
        return EmailReference.objects.create(
            owner=owner,
            external_message_id=kwargs.pop("external_message_id", f"msg-{subject}"),
            subject=subject,
            sender=sender,
            received_at=kwargs.pop("received_at", timezone.now()),
            **kwargs,
        )

    return factory


def sample_jpeg(text: str = "FACTURA") -> bytes:
    """Imagine generata determinist, fara fisiere binare in repository."""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (900, 1200), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([40, 40, 860, 1160], outline="black", width=3)
    draw.text((70, 120), text, fill="black")
    draw.text((70, 220), "DATA LIMITA DE PLATA 06.09.2026", fill="black")
    draw.text((70, 300), "TOTAL DE PLATA 84,20 lei", fill="black")
    buffer = io.BytesIO()
    image.save(buffer, "JPEG")
    return buffer.getvalue()


@pytest.fixture
def sample_image():
    return sample_jpeg


@pytest.fixture
def sample_audio():
    """WAV valid, generat local."""

    def factory(seconds: float = 1.0) -> bytes:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(8000)
            handle.writeframes(b"\x00\x00" * int(8000 * seconds))
        return buffer.getvalue()

    return factory


@pytest.fixture
def demo_source():
    return Source.MANUAL
