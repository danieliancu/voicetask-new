"""Orchestrarea pipeline-ului OCR pentru un document salvat."""

from __future__ import annotations

import logging

import cv2
from django.core.files.base import ContentFile
from django.utils import timezone
from PIL import UnidentifiedImageError

from apps.core.providers.base import ProviderError
from apps.core.providers.registry import get_provider
from apps.documents.models import ScannedDocument
from apps.documents.pipeline import extract as extract_module
from apps.documents.pipeline import preprocess

logger = logging.getLogger("voicetask.documents")


def process(document: ScannedDocument) -> ScannedDocument:
    """Ruleaza intreg pipeline-ul si salveaza rezultatul in document.

    Nu logam niciodata textul recunoscut: poate contine date personale.
    """
    from django.conf import settings

    ScannedDocument.all_objects.filter(pk=document.pk).update(
        processing_status=ScannedDocument.Status.PROCESSING, processing_error=""
    )
    document.refresh_from_db()

    try:
        with document.original_image.open("rb") as handle:
            raw = handle.read()
    except (OSError, ValueError) as exc:
        return _fail(document, "Fotografia nu a putut fi citită.", exc)

    try:
        prepared = preprocess.run(raw, max_side=settings.OCR_MAX_SIDE_PX)
    except (cv2.error, UnidentifiedImageError, ValueError, OSError) as exc:
        return _fail(document, "Imaginea nu a putut fi procesată.", exc)

    try:
        jpeg = prepared.to_jpeg()
        document.processed_image.save(f"procesat-{document.pk}.jpg", ContentFile(jpeg), save=False)
    except ValueError as exc:
        logger.warning("imaginea procesata nu a putut fi salvata: %s", type(exc).__name__)

    provider = get_provider("ocr")
    try:
        result = provider.recognize(jpeg, languages=settings.OCR_LANGUAGES)
    except ProviderError as exc:
        return _fail(document, exc.user_message, exc)

    extraction = extract_module.extract(result.text, result.lines)

    document.extracted_text = result.text
    document.extracted_data = extraction.as_dict()
    document.ocr_confidence = result.mean_confidence
    document.ocr_provider = result.provider
    document.document_type = extraction.document_type
    if not document.title:
        document.title = extraction.title[:200]
    document.processing_status = ScannedDocument.Status.READY
    document.processing_error = ""
    document.save()

    logger.info(
        "document procesat id=%s provider=%s incredere=%.2f campuri=%d deskew=%s",
        document.pk,
        result.provider,
        result.mean_confidence,
        len(extraction.fields),
        prepared.deskewed,
    )
    return document


def _fail(document: ScannedDocument, message: str, exc: Exception) -> ScannedDocument:
    logger.warning("procesare esuata id=%s tip=%s", document.pk, type(exc).__name__)
    ScannedDocument.all_objects.filter(pk=document.pk).update(
        processing_status=ScannedDocument.Status.FAILED,
        processing_error=message[:300],
        updated_at=timezone.now(),
    )
    document.refresh_from_db()
    return document
