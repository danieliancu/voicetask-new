"""Generarea programata a rezumatelor."""

from __future__ import annotations

import logging

from celery import shared_task
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.accounts.models import UserPreference
from apps.daily_brief import services

logger = logging.getLogger("voicetask.brief")


@shared_task(name="daily_brief.generate_scheduled_briefs", ignore_result=True)
def generate_scheduled_briefs() -> int:
    """Genereaza rezumatul pentru utilizatorii a caror ora preferata tocmai a trecut.

    Este idempotent: `get_or_create_brief` nu reface nimic daca datele nu s-au
    schimbat, deci rularea repetata nu costa nimic.
    """
    now = timezone.localtime()
    generated = 0
    for prefs in UserPreference.objects.select_related("user").all():
        if prefs.brief_time > now.time():
            continue
        services.get_or_create_brief(prefs.user, now.date())
        generated += 1
    return generated


@shared_task(name="daily_brief.generate_for_user", ignore_result=True)
def generate_for_user(user_id: int, force: bool = False) -> bool:
    User = get_user_model()
    user = User.objects.filter(pk=user_id).first()
    if user is None:
        return False
    services.get_or_create_brief(user, force=force)
    return True
