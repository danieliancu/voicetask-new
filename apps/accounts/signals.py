"""Fiecare utilizator primeste automat un rand de preferinte."""

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.accounts.models import UserPreference


@receiver(post_save, sender=settings.AUTH_USER_MODEL, dispatch_uid="creeaza_preferinte")
def create_preferences(sender, instance, created, **kwargs):
    if created:
        UserPreference.objects.get_or_create(user=instance)
