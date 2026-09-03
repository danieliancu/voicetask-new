from django.apps import AppConfig


class SchedulingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.scheduling"
    label = "scheduling"
    verbose_name = "Programări"

    def ready(self):
        from apps.scheduling import search_sources  # noqa: F401
