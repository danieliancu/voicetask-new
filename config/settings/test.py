"""Setari pentru teste: totul pe provideri mock, fara retea, fara Redis."""

import tempfile

from .base import *
from .base import PROVIDERS

DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}

MEDIA_ROOT = tempfile.mkdtemp(prefix="voicetask-test-media-")

CELERY_TASK_ALWAYS_EAGER = True
AI_ENABLED = False

PROVIDERS = {
    **PROVIDERS,
    "transcription": "apps.assistant.providers.mock_transcription.MockTranscriptionProvider",
    "intent": "apps.assistant.providers.rule_based.RuleBasedIntentParser",
    "ocr": "apps.documents.providers.mock.MockOCRProvider",
    "tts": "apps.daily_brief.providers.mock_tts.MockTTSProvider",
    "gmail": "apps.integrations.providers.mock_gmail.MockGmailProvider",
    "calendar": "apps.integrations.providers.mock_calendar.MockCalendarProvider",
    "notification": "apps.notifications.providers.console.ConsoleNotificationProvider",
}

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

LOGGING = {"version": 1, "disable_existing_loggers": False, "root": {"handlers": []}}
