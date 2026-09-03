from django.apps import AppConfig


class DailyBriefConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.daily_brief"
    label = "daily_brief"
    verbose_name = "Rezumat zilnic"

    def ready(self):
        from apps.daily_brief import signals  # noqa: F401
