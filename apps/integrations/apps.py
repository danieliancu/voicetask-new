from django.apps import AppConfig


class IntegrationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.integrations"
    label = "integrations"
    verbose_name = "Integrări"

    def ready(self):
        from apps.integrations import search_sources  # noqa: F401
