"""Validarea fisierelor incarcate: tip real, dimensiune, nume sigur."""

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.core.files import safe_filename, validate_audio_upload, validate_image_upload
from apps.documents.models import ScannedDocument

pytestmark = pytest.mark.django_db

MB = 1024 * 1024


def upload(name: str, content: bytes, content_type: str = "image/jpeg"):
    return SimpleUploadedFile(name, content, content_type=content_type)


def test_imaginea_valida_este_acceptata(sample_image):
    detected = validate_image_upload(upload("foto.jpg", sample_image()), max_bytes=12 * MB)
    assert detected.content_type == "image/jpeg"
    assert detected.extension == "jpg"
    assert len(detected.sha256) == 64


def test_text_redenumit_jpg_este_respins():
    """Tipul se determina din octeti, nu din extensie sau din antetul clientului."""
    with pytest.raises(ValidationError):
        validate_image_upload(upload("fals.jpg", b"nu sunt o imagine"), max_bytes=12 * MB)


def test_fisierul_gol_este_respins():
    with pytest.raises(ValidationError):
        validate_image_upload(upload("gol.jpg", b""), max_bytes=12 * MB)


def test_fisierul_prea_mare_este_respins(sample_image):
    with pytest.raises(ValidationError) as exc:
        validate_image_upload(upload("mare.jpg", sample_image()), max_bytes=100)
    assert "depășește" in str(exc.value)


def test_png_si_webp_sunt_acceptate():
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 100
    assert validate_image_upload(upload("x.png", png), max_bytes=12 * MB).extension == "png"

    webp = b"RIFF" + b"0000" + b"WEBP" + b"0" * 100
    assert validate_image_upload(upload("x.webp", webp), max_bytes=12 * MB).extension == "webp"


def test_audio_webm_si_wav_sunt_acceptate(sample_audio):
    webm = b"\x1aE\xdf\xa3" + b"0" * 100
    assert validate_audio_upload(upload("a.webm", webm), max_bytes=20 * MB).extension == "webm"
    wav = validate_audio_upload(upload("a.wav", sample_audio()), max_bytes=20 * MB)
    assert wav.extension == "wav"


def test_imaginea_nu_trece_drept_audio(sample_image):
    with pytest.raises(ValidationError):
        validate_audio_upload(upload("x.wav", sample_image()), max_bytes=20 * MB)


def test_numele_de_fisier_este_generat_de_server():
    assert safe_filename("../../etc/passwd").endswith(".etcpasswd") is False
    name = safe_filename("jpg")
    assert name.endswith(".jpg")
    assert "/" not in name and "\\" not in name and ".." not in name


def test_numele_periculos_nu_ajunge_pe_disc(auth_client, user, sample_image):
    response = auth_client.post(
        reverse("documents:upload"),
        {"imagine": upload("../../../evil.jpg", sample_image())},
    )

    assert response.status_code == 201
    document = ScannedDocument.objects.for_user(user).get()
    assert ".." not in document.original_image.name
    assert "evil" not in document.original_image.name


def test_incarcarea_aceleiasi_imagini_nu_creeaza_duplicat(auth_client, user, sample_image):
    payload = sample_image()

    prima = auth_client.post(reverse("documents:upload"), {"imagine": upload("a.jpg", payload)})
    a_doua = auth_client.post(reverse("documents:upload"), {"imagine": upload("b.jpg", payload)})

    assert prima.json()["duplicat"] is False
    assert a_doua.json()["duplicat"] is True
    assert ScannedDocument.objects.for_user(user).count() == 1


def test_incarcarea_fara_fisier_este_respinsa(auth_client):
    response = auth_client.post(reverse("documents:upload"), {})
    assert response.status_code == 400
    assert "eroare" in response.json()


def test_fotografia_originala_cere_proprietar(other_client, user, document_factory):
    document = document_factory(user)
    response = other_client.get(reverse("documents:original_image", args=[document.pk]))
    assert response.status_code == 404
