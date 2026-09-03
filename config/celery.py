"""Configurarea Celery. In dev taskurile ruleaza eager, deci Redis nu este necesar."""

import os

from celery import Celery
from celery.schedules import crontab

from config.env import default_settings_module

os.environ.setdefault("DJANGO_SETTINGS_MODULE", default_settings_module())

celery_app = Celery("voicetask")
celery_app.config_from_object("django.conf:settings", namespace="CELERY")
celery_app.autodiscover_tasks()

celery_app.conf.beat_schedule = {
    "trimite-alarme-scadente": {
        "task": "notifications.dispatch_due_reminders",
        "schedule": crontab(minute="*"),
    },
    "genereaza-rezumate-zilnice": {
        "task": "daily_brief.generate_scheduled_briefs",
        "schedule": crontab(minute="*/15"),
    },
    "sincronizeaza-integrari": {
        "task": "integrations.sync_all_accounts",
        "schedule": crontab(minute="*/30"),
    },
    "goleste-cosul-de-gunoi": {
        "task": "core.purge_trashed",
        "schedule": crontab(hour=3, minute=15),
    },
    "sterge-schitele-expirate": {
        "task": "core.purge_expired_drafts",
        "schedule": crontab(minute=7),
    },
    "sterge-fisierele-vechi": {
        "task": "core.purge_old_media",
        "schedule": crontab(hour=3, minute=40),
    },
}
