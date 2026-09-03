from django.apps import AppConfig


class DocumentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.documents"
    label = "documents"
    verbose_name = "Documente"

    def ready(self):
        from apps.documents import search_sources  # noqa: F401
