from django.apps import AppConfig


class NotesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.notes"
    label = "notes"
    verbose_name = "Notițe"

    def ready(self):
        from apps.notes import search_sources  # noqa: F401
