"""Manageri pentru soft-delete si izolare pe utilizator."""

from __future__ import annotations

from django.db import models
from django.utils import timezone


class SoftDeleteQuerySet(models.QuerySet):
    def alive(self):
        return self.filter(deleted_at__isnull=True)

    def dead(self):
        return self.filter(deleted_at__isnull=False)

    def for_user(self, user):
        return self.filter(owner=user)

    def delete(self):
        """Stergere in masa = soft delete."""
        return self.update(deleted_at=timezone.now())

    def restore(self):
        return self.update(deleted_at=None, deleted_by_cascade=False)

    def hard_delete(self):
        return super().delete()


class AliveManager(models.Manager.from_queryset(SoftDeleteQuerySet)):
    """Managerul implicit: nu vede niciodata obiectele din cos."""

    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class AllObjectsManager(models.Manager.from_queryset(SoftDeleteQuerySet)):
    """Vede si obiectele din cos. Folosit de cos, de admin si de taskul de purjare."""


class OwnedQuerySet(models.QuerySet):
    def for_user(self, user):
        return self.filter(owner=user)


OwnedManager = models.Manager.from_queryset(OwnedQuerySet)
