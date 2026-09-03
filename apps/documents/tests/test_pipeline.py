"""Pipeline-ul OCR: preprocesare, recunoastere, extractie, confirmare."""

import pytest
from django.urls import reverse

from apps.core.providers.registry import override_provider
from apps.documents.models import ScannedDocument
from apps.documents.pipeline import preprocess
from apps.documents.pipeline.service import process
from apps.notes.models import Note
from apps.scheduling.models import Appointment, Reminder

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------- preprocesare


def test_preprocesarea_produce_imagine_valida(sample_image):
    result = preprocess.run(sample_image(), max_side=800)

    assert result.width > 0 and result.height > 0
    assert max(result.width, result.height) <= 800
    assert result.resized
    assert result.to_jpeg().startswith(b"\xff\xd8\xff")


def test_detectia_documentului_raspunde_fara_sa_arunce(sample_image):
    result = preprocess.detect_only(sample_image())
    assert set(result) == {"detected", "quad", "width", "height"}
    assert isinstance(result["detected"], bool)


def test_imaginea_corupta_este_respinsa():
    from PIL import UnidentifiedImageError

    with pytest.raises((UnidentifiedImageError, OSError, ValueError)):
        preprocess.run(b"nu sunt o imagine")


# --------------------------------------------------------------------- procesare


def test_procesarea_completa_umple_documentul(user, document_factory):
    document = document_factory(user)

    process(document)

    document.refresh_from_db()
    assert document.processing_status == ScannedDocument.Status.READY
    assert document.extracted_text
    assert document.extracted_data
    assert document.ocr_confidence > 0


def test_esecul_providerului_marcheaza_documentul_nu_arunca(user, document_factory):
    from apps.core.providers.base import OCRProvider, ProviderUnavailable

    class ProviderStricat(OCRProvider):
        name = "stricat"

        def recognize(self, image_bytes, *, languages=None):
            raise ProviderUnavailable("Motorul OCR nu este instalat.")

    document = document_factory(user)
    with override_provider("ocr", ProviderStricat()):
        process(document)

    document.refresh_from_db()
    assert document.processing_status == ScannedDocument.Status.FAILED
    assert document.processing_error


def test_procesarea_nu_creeaza_nimic_automat(user, document_factory):
    """Nicio alarma sau programare nu apare fara confirmarea utilizatorului."""
    document = document_factory(user)

    process(document)

    assert Reminder.objects.for_user(user).count() == 0
    assert Appointment.objects.for_user(user).count() == 0
    assert Note.objects.for_user(user).count() == 0


# --------------------------------------------------------------------- confirmare


def test_confirmarea_creeaza_notita_si_alarma(auth_client, user, document_factory):
    document = document_factory(user)
    process(document)

    response = auth_client.post(
        reverse("documents:confirm", args=[document.pk]),
        {
            "title": "Factura energie",
            "document_type": "invoice",
            "due_date": "2026-09-06",
            "event_time": "",
            "amount": "84.20",
            "currency": "lei",
            "location": "",
            "person": "",
            "notes": "",
            "action": "reminder",
            "reminder_offset": "1440",
        },
    )

    assert response.status_code == 302
    document.refresh_from_db()
    assert document.processing_status == ScannedDocument.Status.CONFIRMED
    assert Note.objects.for_user(user).count() == 1
    reminder = Reminder.objects.for_user(user).get()
    assert reminder.document_id == document.pk


def test_confirmarea_fara_data_pentru_alarma_esueaza(auth_client, user, document_factory):
    document = document_factory(user)
    process(document)

    response = auth_client.post(
        reverse("documents:confirm", args=[document.pk]),
        {
            "title": "Factura",
            "document_type": "invoice",
            "due_date": "",
            "action": "reminder",
            "reminder_offset": "1440",
        },
    )

    assert response.status_code == 400
    assert Reminder.objects.for_user(user).count() == 0


def test_confirmarea_ca_programare_creeaza_evenimentul(auth_client, user, document_factory):
    document = document_factory(user)
    process(document)

    auth_client.post(
        reverse("documents:confirm", args=[document.pk]),
        {
            "title": "Invitație serbare",
            "document_type": "invitation",
            "due_date": "2026-09-14",
            "event_time": "10:00",
            "amount": "",
            "currency": "",
            "location": "Școala Nr. 12",
            "person": "",
            "notes": "",
            "action": "appointment",
            "reminder_offset": "1440",
        },
    )

    appointment = Appointment.objects.for_user(user).get()
    assert appointment.location == "Școala Nr. 12"
    assert appointment.source_document_id == document.pk


def test_campurile_nesigure_sunt_marcate(user, document_factory):
    from apps.documents.forms import ExtractionConfirmForm

    document = document_factory(user)
    document.extracted_data = {
        "due_date": {"value": "2026-09-06", "confidence": 0.3},
        "amount": {"value": 84.2, "confidence": 0.95},
    }
    document.save()

    form = ExtractionConfirmForm(document=document, user=user)

    assert "due_date" in form.uncertain_fields()
    assert "amount" not in form.uncertain_fields()


@pytest.mark.slow
def test_motorul_rapidocr_recunoaste_text(sample_image):
    """Verificare a motorului OCR real. Se sare daca nu este instalat."""
    from apps.documents.providers.rapid_ocr import RapidOCRProvider

    provider = RapidOCRProvider()
    if not provider.is_available():
        pytest.skip("rapidocr-onnxruntime nu este instalat.")

    result = provider.recognize(sample_image("FACTURA ENERGIE"))

    assert result.provider == "rapidocr"
    assert isinstance(result.text, str)
