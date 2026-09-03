from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    label = "core"
    verbose_name = "Nucleu"

    def ready(self):
        from apps.core import checks  # noqa: F401  (inregistreaza system checks)
