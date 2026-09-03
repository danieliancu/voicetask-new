"""Validarea si denumirea sigura a fisierelor incarcate.

Tipul se determina din primii octeti, nu din `content_type` trimis de browser si
nu din extensia numelui de fisier.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import date

from django.core.exceptions import ValidationError

IMAGE_SIGNATURES: tuple[tuple[bytes, str, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
    (b"GIF87a", "image/gif", "gif"),
    (b"GIF89a", "image/gif", "gif"),
    (b"BM", "image/bmp", "bmp"),
)

AUDIO_SIGNATURES: tuple[tuple[bytes, str, str], ...] = (
    (b"\x1aE\xdf\xa3", "audio/webm", "webm"),
    (b"OggS", "audio/ogg", "ogg"),
    (b"ID3", "audio/mpeg", "mp3"),
    (b"\xff\xfb", "audio/mpeg", "mp3"),
    (b"\xff\xf1", "audio/aac", "aac"),
)

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class DetectedFile:
    content_type: str
    extension: str
    size: int
    sha256: str


def _read_head(upload, length: int = 32) -> bytes:
    upload.seek(0)
    head = upload.read(length)
    upload.seek(0)
    return head


def _sha256(upload) -> str:
    digest = hashlib.sha256()
    upload.seek(0)
    for chunk in upload.chunks():
        digest.update(chunk)
    upload.seek(0)
    return digest.hexdigest()


def _match_signature(head: bytes, table) -> tuple[str, str] | None:
    for signature, content_type, extension in table:
        if head.startswith(signature):
            return content_type, extension
    return None


def _detect_riff(head: bytes) -> tuple[str, str] | None:
    """WAV si WEBP folosesc containere RIFF, respectiv ISO-BMFF."""
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "audio/wav", "wav"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp", "webp"
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"heic", b"heix", b"hevc", b"mif1"):
            return "image/heic", "heic"
        return "audio/mp4", "m4a"
    return None


def validate_image_upload(upload, *, max_bytes: int) -> DetectedFile:
    if upload is None:
        raise ValidationError("Nu a fost trimis niciun fișier.")
    if upload.size == 0:
        raise ValidationError("Fișierul este gol.")
    if upload.size > max_bytes:
        limit_mb = max_bytes / (1024 * 1024)
        raise ValidationError(f"Imaginea depășește limita de {limit_mb:.0f} MB.")
    head = _read_head(upload)
    detected = _match_signature(head, IMAGE_SIGNATURES) or _detect_riff(head)
    if detected is None or not detected[0].startswith("image/"):
        raise ValidationError("Fișierul nu este o imagine validă (JPEG, PNG, WebP sau HEIC).")
    return DetectedFile(detected[0], detected[1], upload.size, _sha256(upload))


def validate_audio_upload(upload, *, max_bytes: int) -> DetectedFile:
    if upload is None:
        raise ValidationError("Nu a fost trimisă nicio înregistrare.")
    if upload.size == 0:
        raise ValidationError("Înregistrarea este goală.")
    if upload.size > max_bytes:
        limit_mb = max_bytes / (1024 * 1024)
        raise ValidationError(f"Înregistrarea depășește limita de {limit_mb:.0f} MB.")
    head = _read_head(upload)
    detected = _match_signature(head, AUDIO_SIGNATURES) or _detect_riff(head)
    if detected is None or not detected[0].startswith("audio/"):
        raise ValidationError("Formatul audio nu este acceptat (webm, ogg, mp4, wav sau mp3).")
    return DetectedFile(detected[0], detected[1], upload.size, _sha256(upload))


def safe_filename(extension: str) -> str:
    """Nume complet generat de server: nimic din numele trimis de client nu supravietuieste."""
    clean = _SAFE_NAME.sub("", extension).lower()[:8] or "bin"
    return f"{uuid.uuid4().hex}.{clean}"


def upload_to_scans(instance, filename: str) -> str:
    today = date.today()
    return f"scans/{instance.owner_id}/{today:%Y/%m}/{safe_filename(filename.rsplit('.', 1)[-1])}"


def upload_to_processed(instance, filename: str) -> str:
    today = date.today()
    return f"scans/{instance.owner_id}/{today:%Y/%m}/proc-{safe_filename('jpg')}"


def upload_to_voice(instance, filename: str) -> str:
    today = date.today()
    return f"voice/{instance.owner_id}/{today:%Y/%m}/{safe_filename(filename.rsplit('.', 1)[-1])}"


def upload_to_brief_audio(instance, filename: str) -> str:
    """Numele este generat de server si contine amprenta textului: pe el se
    bazeaza cache-ul audio, deci nu il inlocuim cu unul aleator."""
    clean = _SAFE_NAME.sub("", filename)[:80] or safe_filename("wav")
    return f"brief/{instance.owner_id}/{clean}"


def delete_associated_files(obj) -> None:
    """Sterge de pe disc fisierele atasate unui obiect purjat definitiv."""
    from django.db.models import FileField

    for field in obj._meta.get_fields():
        if isinstance(field, FileField):
            file = getattr(obj, field.name, None)
            if file:
                file.delete(save=False)
