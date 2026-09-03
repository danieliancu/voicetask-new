"""Generarea si cache-ul rezumatului zilnic."""

from __future__ import annotations

import hashlib
import logging
from datetime import date

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import UserPreference
from apps.core.providers.base import ProviderError
from apps.core.providers.registry import get_provider
from apps.daily_brief import polish as polish_module
from apps.daily_brief import render
from apps.daily_brief import snapshot as snapshot_module
from apps.daily_brief.models import DailyBrief

logger = logging.getLogger("voicetask.brief")


def get_or_create_brief(user, day: date | None = None, *, force: bool = False) -> DailyBrief:
    """Returneaza rezumatul zilei, regenerandu-l doar daca datele s-au schimbat."""
    day = day or timezone.localdate()
    prefs = UserPreference.for_user(user)
    data = snapshot_module.build_snapshot(user, day)
    digest = snapshot_module.source_hash(data)

    with transaction.atomic():
        brief, created = DailyBrief.objects.select_for_update().get_or_create(
            owner=user,
            date=day,
            defaults={"source_hash": digest, "status": DailyBrief.Status.PENDING},
        )
        unchanged = (
            not created
            and brief.source_hash == digest
            and brief.status == DailyBrief.Status.READY
            and not force
        )
        if unchanged:
            return brief

        brief.snapshot = data
        brief.source_hash = digest
        brief.generated_text = render.render_text(data)
        brief.polished_text = ""
        brief.polish_rejected_reason = ""

        if prefs.brief_polish_enabled:
            result = polish_module.polish(brief.generated_text)
            if result.accepted:
                brief.polished_text = result.text
            else:
                brief.polish_rejected_reason = result.reason

        brief.status = DailyBrief.Status.READY
        brief.generated_at = timezone.now()
        brief.save()

    _refresh_audio(brief, prefs)
    return brief


def _refresh_audio(brief: DailyBrief, prefs: UserPreference) -> None:
    """Audio se regenereaza doar cand textul s-a schimbat (cache pe continut)."""
    from django.conf import settings

    dezactivat = not (settings.BRIEF_AUDIO_ENABLED and prefs.brief_audio_enabled)
    # O zi fara nimic nu are ce sa fie ascultata: nu generam audio si nu afisam
    # butonul de redare. Vezi `DailyBrief.has_content`.
    if dezactivat or not brief.has_content:
        _drop_audio(brief)
        return

    text_digest = hashlib.sha256(brief.text.encode("utf-8")).hexdigest()[:16]
    if brief.audio_file and text_digest in brief.audio_file.name:
        return


    try:
        speech = get_provider("tts").synthesize(brief.text)
    except ProviderError as exc:
        logger.warning("audio rezumat indisponibil: %s", type(exc).__name__)
        return

    if brief.audio_file:
        brief.audio_file.delete(save=False)
    brief.audio_file.save(
        f"rezumat-{brief.date:%Y%m%d}-{text_digest}.{speech.extension}",
        ContentFile(speech.audio),
        save=False,
    )
    brief.audio_duration_ms = speech.duration_ms
    brief.save(update_fields=["audio_file", "audio_duration_ms", "updated_at"])


def _drop_audio(brief: DailyBrief) -> None:
    """Sterge fisierul audio si referinta la el."""
    if not brief.audio_file:
        return
    brief.audio_file.delete(save=False)
    brief.audio_file = ""
    brief.audio_duration_ms = 0
    DailyBrief.objects.filter(pk=brief.pk).update(audio_file="", audio_duration_ms=0)


def invalidate(user, day: date | None = None) -> None:
    """Marcheaza rezumatul ca invalid; urmatoarea cerere il reconstruieste."""
    day = day or timezone.localdate()
    DailyBrief.objects.filter(owner=user, date=day).update(
        status=DailyBrief.Status.PENDING, source_hash=""
    )


def ask(user, brief: DailyBrief, question: str):
    """Raspunde la o intrebare despre zi, exclusiv din instantaneul salvat."""
    from apps.daily_brief.models import BriefQuestion

    answer = render.answer_question(brief.snapshot or {}, question)
    return BriefQuestion.objects.create(
        owner=user, brief=brief, question=question[:300], answer=answer
    )
