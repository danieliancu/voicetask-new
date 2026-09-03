"""Procesarea OCR ruleaza asincron ca incarcarea sa raspunda imediat."""

from __future__ import annotations

from celery import shared_task

from apps.documents.models import ScannedDocument


@shared_task(name="documents.process_document", ignore_result=True, bind=True, max_retries=2)
def process_document(self, document_id: int) -> str:
    from apps.documents.pipeline.service import process

    document = ScannedDocument.all_objects.filter(pk=document_id).first()
    if document is None:
        return "inexistent"
    process(document)
    return document.processing_status
