"""Setari comune tuturor mediilor."""

from __future__ import annotations

import os
from pathlib import Path

from config.env import bootstrap

bootstrap()

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def env_bool(name: str, default: bool = False) -> bool:
    return (env(name, str(default)) or "").strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    raw = env(name)
    try:
        return int(raw) if raw not in (None, "") else default
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    raw = env(name)
    try:
        return float(raw) if raw not in (None, "") else default
    except ValueError:
        return default


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in (env(name, default) or "").split(",") if item.strip()]


# --------------------------------------------------------------------------- baza

SECRET_KEY = env("DJANGO_SECRET_KEY", "insecure-doar-pentru-dev")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "django_htmx",
    "apps.core",
    "apps.accounts",
    "apps.notes",
    "apps.scheduling",
    "apps.documents",
    "apps.integrations",
    "apps.assistant",
    "apps.daily_brief",
    "apps.notifications",
    "apps.search",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.accounts.context_processors.user_context",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "OPTIONS": {"init_command": "PRAGMA journal_mode=WAL;"},
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:home"
LOGOUT_REDIRECT_URL = "accounts:login"

# Interfata este exclusiv in romana; `LocaleMiddleware` lipseste intentionat
# din MIDDLEWARE, ca antetul Accept-Language al browserului sa nu comute limba.
LANGUAGE_CODE = "ro"
TIME_ZONE = "Europe/Bucharest"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "voicetask-default",
    }
}

MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"

# --------------------------------------------------------------------------- provideri

PROVIDERS = {
    "transcription": env(
        "PROVIDER_TRANSCRIPTION",
        "apps.assistant.providers.mock_transcription.MockTranscriptionProvider",
    ),
    "intent": env(
        "PROVIDER_INTENT",
        "apps.assistant.providers.rule_based.RuleBasedIntentParser",
    ),
    "ocr": env("PROVIDER_OCR", "apps.documents.providers.mock.MockOCRProvider"),
    "tts": env("PROVIDER_TTS", "apps.daily_brief.providers.mock_tts.MockTTSProvider"),
    "gmail": env("PROVIDER_GMAIL", "apps.integrations.providers.mock_gmail.MockGmailProvider"),
    "calendar": env(
        "PROVIDER_CALENDAR",
        "apps.integrations.providers.mock_calendar.MockCalendarProvider",
    ),
    "notification": env(
        "PROVIDER_NOTIFICATION",
        "apps.notifications.providers.console.ConsoleNotificationProvider",
    ),
}

# Providerii folositi cand AI_ENABLED este False, indiferent de PROVIDERS.
PROVIDERS_OFFLINE = {
    "transcription": "apps.assistant.providers.mock_transcription.MockTranscriptionProvider",
    "intent": "apps.assistant.providers.rule_based.RuleBasedIntentParser",
    "tts": "apps.daily_brief.providers.mock_tts.MockTTSProvider",
}

AI_ENABLED = env_bool("AI_ENABLED", False)
OPENAI_API_KEY = env("OPENAI_API_KEY", "")
OPENAI_BASE_URL = env("OPENAI_BASE_URL", "") or None
OPENAI_MODEL_INTENT = env("OPENAI_MODEL_INTENT", "gpt-4o-mini")
OPENAI_MODEL_TRANSCRIBE = env("OPENAI_MODEL_TRANSCRIBE", "whisper-1")
OPENAI_MODEL_TTS = env("OPENAI_MODEL_TTS", "gpt-4o-mini-tts")
OPENAI_TTS_VOICE = env("OPENAI_TTS_VOICE", "alloy")
PROVIDER_TIMEOUT_SECONDS = env_int("PROVIDER_TIMEOUT_SECONDS", 30)
PROVIDER_MAX_RETRIES = env_int("PROVIDER_MAX_RETRIES", 2)

OCR_LANGUAGES = env_list("OCR_LANGUAGES", "ro,en")
OCR_MAX_SIDE_PX = env_int("OCR_MAX_SIDE_PX", 2000)

GOOGLE_CLIENT_ID = env("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = env("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = env(
    "GOOGLE_REDIRECT_URI", "http://127.0.0.1:8000/integrari/google/callback/"
)
GMAIL_SCOPE_LEVEL = env("GMAIL_SCOPE_LEVEL", "metadata")  # metadata | readonly

VAPID_PUBLIC_KEY = env("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = env("VAPID_PRIVATE_KEY", "")
VAPID_CONTACT_EMAIL = env("VAPID_CONTACT_EMAIL", "")

TOKEN_ENCRYPTION_KEY = env("TOKEN_ENCRYPTION_KEY", "")

# --------------------------------------------------------------------------- aplicatie

TRASH_RETENTION_DAYS = env_int("TRASH_RETENTION_DAYS", 30)
VOICE_AUDIO_RETENTION_DAYS = env_int("VOICE_AUDIO_RETENTION_DAYS", 7)
DRAFT_TTL_MINUTES = env_int("DRAFT_TTL_MINUTES", 60)

MAX_UPLOAD_IMAGE_BYTES = env_int("MAX_UPLOAD_IMAGE_BYTES", 12 * 1024 * 1024)
MAX_UPLOAD_AUDIO_BYTES = env_int("MAX_UPLOAD_AUDIO_BYTES", 20 * 1024 * 1024)
DATA_UPLOAD_MAX_MEMORY_SIZE = 15 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
FILE_UPLOAD_PERMISSIONS = 0o644

RATE_LIMITS = {
    "voice": (env_int("RATE_VOICE_MAX", 20), env_int("RATE_VOICE_WINDOW", 300)),
    "ocr": (env_int("RATE_OCR_MAX", 20), env_int("RATE_OCR_WINDOW", 300)),
    "ai": (env_int("RATE_AI_MAX", 30), env_int("RATE_AI_WINDOW", 300)),
    "search": (env_int("RATE_SEARCH_MAX", 120), env_int("RATE_SEARCH_WINDOW", 60)),
}

# Praguri pentru interpretarea comenzilor vocale.
INTENT_CONFIDENCE_AUTOFILL = env_float("INTENT_CONFIDENCE_AUTOFILL", 0.55)
INTENT_CONFIDENCE_CLARIFY = env_float("INTENT_CONFIDENCE_CLARIFY", 0.40)
OCR_FIELD_CONFIDENCE_WARN = env_float("OCR_FIELD_CONFIDENCE_WARN", 0.65)

BRIEF_POLISH_ENABLED = env_bool("BRIEF_POLISH_ENABLED", False)
BRIEF_AUDIO_ENABLED = env_bool("BRIEF_AUDIO_ENABLED", True)

SW_CACHE_VERSION = env("SW_CACHE_VERSION", "2")

# --------------------------------------------------------------------------- celery

CELERY_BROKER_URL = env("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", "") or None
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", False)
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TIMEZONE = TIME_ZONE
CELERY_ENABLE_UTC = True
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

# --------------------------------------------------------------------------- securitate

CSRF_COOKIE_HTTPONLY = False  # HTMX citeste tokenul din cookie
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "[{levelname}] {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": env("DJANGO_LOG_LEVEL", "INFO")},
    "loggers": {
        # Nu logam niciodata continut: transcrieri, text OCR, emailuri, tokenuri.
        "voicetask": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
