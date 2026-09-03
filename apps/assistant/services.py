"""Fluxul complet: audio sau text → transcriere → intentie → schita editabila."""

from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.accounts.models import UserPreference
from apps.assistant import policy, resolver
from apps.assistant.models import IntentDraft, VoiceCapture
from apps.assistant.schemas import Intent, IntentResult, IntentValidationError, parse_result
from apps.core.providers.base import ProviderError
from apps.core.providers.context import IntentContext
from apps.core.providers.registry import get_provider

logger = logging.getLogger("voicetask.assistant")


def build_context(user, *, mode: str = "create", target_kind=None, target_id=None) -> IntentContext:
    prefs = UserPreference.for_user(user)
    return IntentContext(
        now=timezone.localtime(),
        timezone_name=prefs.timezone,
        known_items=resolver.known_items(user),
        default_reminder_offset=prefs.default_reminder_offset,
        mode=mode,
        target_kind=target_kind,
        target_id=target_id,
    )


def transcribe(capture: VoiceCapture, audio: bytes) -> VoiceCapture:
    """Transcrie inregistrarea. Nu logam niciodata textul rezultat."""
    VoiceCapture.all_objects.filter(pk=capture.pk).update(
        status=VoiceCapture.Status.TRANSCRIBING
    )
    provider = get_provider("transcription")
    try:
        result = provider.transcribe(audio, content_type=capture.content_type or "audio/webm")
    except ProviderError as exc:
        capture.status = VoiceCapture.Status.FAILED
        capture.error = exc.user_message
        capture.save(update_fields=["status", "error", "updated_at"])
        logger.warning("transcriere esuata capture=%s tip=%s", capture.uid, type(exc).__name__)
        return capture

    capture.transcript = result.text
    capture.transcript_confidence = result.confidence
    capture.duration_ms = result.duration_ms
    capture.status = VoiceCapture.Status.PARSING
    capture.save(
        update_fields=[
            "transcript",
            "transcript_confidence",
            "duration_ms",
            "status",
            "updated_at",
        ]
    )
    return capture


def interpret(
    user,
    text: str,
    *,
    capture: VoiceCapture | None = None,
    mode: str = "create",
    target_kind: str | None = None,
    target_id: int | None = None,
) -> IntentDraft:
    """Interpreteaza textul si creeaza schita. Nu salveaza nimic in aplicatie."""
    context = build_context(user, mode=mode, target_kind=target_kind, target_id=target_id)
    provider = get_provider("intent")

    try:
        raw = provider.parse(text, context=context)
    except ProviderError as exc:
        logger.warning("interpretare esuata tip=%s", type(exc).__name__)
        raw = {"intent": Intent.UNKNOWN, "confidence": 0.0}

    try:
        result = parse_result(raw)
    except IntentValidationError as exc:
        logger.warning("schema invalida campuri=%s", exc.fields)
        result = IntentResult(
            intent=Intent.UNKNOWN,
            confidence=0.0,
            clarification_required=True,
            clarification_question="Nu am putut interpreta comanda. Poți reformula?",
        )

    candidates: list[resolver.Candidate] = []
    if result.needs_target and result.target_id is None:
        found_id, found_kind, candidates = resolver.resolve(
            user, result.title or text, kind=result.target_kind or target_kind
        )
        if found_id is not None:
            result = result.model_copy(update={"target_id": found_id, "target_kind": found_kind})

    decision = policy.decide(result, candidate_count=len(candidates))

    draft = IntentDraft.objects.create(
        owner=user,
        capture=capture,
        intent=result.intent,
        payload=result.model_dump(mode="json"),
        confidence=result.confidence,
        status=(
            IntentDraft.Status.NEEDS_CLARIFICATION
            if decision.needs_clarification
            else IntentDraft.Status.DRAFT
        ),
        clarification_question=decision.question,
        candidates=[candidate.as_dict() for candidate in candidates],
        target_kind=result.target_kind or "",
        target_id=result.target_id,
        source_text=text,
        expires_at=timezone.now() + timedelta(minutes=settings.DRAFT_TTL_MINUTES),
    )

    if capture is not None:
        capture.status = VoiceCapture.Status.READY
        capture.save(update_fields=["status", "updated_at"])

    return draft


def process_capture(capture: VoiceCapture, audio: bytes) -> IntentDraft | None:
    capture = transcribe(capture, audio)
    if capture.status == VoiceCapture.Status.FAILED:
        return None
    return interpret(
        capture.owner,
        capture.transcript,
        capture=capture,
        mode=capture.mode,
    )


def result_from_draft(draft: IntentDraft) -> IntentResult:
    return IntentResult.model_validate(draft.payload)
