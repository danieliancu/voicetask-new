"""Setari pentru dezvoltare locala.

Celery ruleaza eager, deci nu este nevoie de Redis pe masina de dezvoltare.
"""

from .base import *
from .base import env_bool, env_list

DEBUG = True
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1],testserver")

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
INTERNAL_IPS = ["127.0.0.1"]

# Fara Redis local: taskurile se executa sincron, in proces.
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", True)

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
