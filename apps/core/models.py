"""Modele abstracte partajate: timestamp, proprietar, soft delete."""

from __future__ import annotations

from typing import ClassVar

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from apps.core.managers import AliveManager, AllObjectsManager, OwnedManager


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField("creat la", auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField("actualizat la", auto_now=True)

    class Meta:
        abstract = True


class OwnedModel(models.Model):
    """Fiecare rand apartine exact unui utilizator."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="proprietar",
        on_delete=models.CASCADE,
        related_name="%(app_label)s_%(class)s_set",
        editable=False,
    )

    objects = OwnedManager()

    class Meta:
        abstract = True


class SoftDeleteModel(models.Model):
    """Stergerea muta randul in cos; purjarea definitiva se face dupa 30 de zile.

    `objects` este declarat primul, deci devine `_default_manager`: managerii inversi
    (`user.notes_note_set`, `appointment.reminders`) exclud automat randurile din cos.
    `Meta.base_manager_name` ramane nesetat intentionat, ca sa poata fi incarcate
    relatiile catre obiecte deja mutate in cos (altfel `refresh_from_db` ar crapa).
    """

    deleted_at = models.DateTimeField(
        "sters la", null=True, blank=True, db_index=True, editable=False
    )
    deleted_by_cascade = models.BooleanField(default=False, editable=False)

    #: Numele acceselor inverse care se sterg / restaureaza impreuna cu obiectul.
    cascade_relations: ClassVar[tuple[str, ...]] = ()

    objects = AliveManager()
    all_objects = AllObjectsManager()

    class Meta:
        abstract = True

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def _cascade_manager(self, relation: str):
        """Managerul nefiltrat al unei relatii inverse (`items`, `reminders`, ...)."""
        return getattr(self, relation)(manager="all_objects")

    def delete(self, using=None, keep_parents=False, *, cascade=True):
        now = timezone.now()
        with transaction.atomic(using=using):
            for relation in self.cascade_relations if cascade else ():
                self._cascade_manager(relation).filter(deleted_at__isnull=True).update(
                    deleted_at=now, deleted_by_cascade=True
                )
            type(self).all_objects.filter(pk=self.pk).update(
                deleted_at=now, deleted_by_cascade=False
            )
        self.deleted_at = now
        return (1, {self._meta.label: 1})

    def restore(self, *, cascade=True):
        with transaction.atomic():
            for relation in self.cascade_relations if cascade else ():
                self._cascade_manager(relation).filter(deleted_by_cascade=True).update(
                    deleted_at=None, deleted_by_cascade=False
                )
            type(self).all_objects.filter(pk=self.pk).update(
                deleted_at=None, deleted_by_cascade=False
            )
        self.deleted_at = None
        self.deleted_by_cascade = False

    def hard_delete(self, using=None):
        return super().delete(using=using)


class OwnedSoftDeleteModel(OwnedModel, SoftDeleteModel):
    """Combinatia folosita de aproape toate modelele de domeniu."""

    objects = AliveManager()
    all_objects = AllObjectsManager()

    class Meta:
        abstract = True


class AuditLog(TimeStampedModel):
    """Urma pentru actiunile sensibile: stergeri, sincronizari externe, conectari."""

    class Action(models.TextChoices):
        DELETE = "delete", "Ștergere"
        RESTORE = "restore", "Restaurare"
        PURGE = "purge", "Purjare definitivă"
        EXTERNAL_WRITE = "external_write", "Scriere în serviciu extern"
        CONNECT = "connect", "Conectare cont"
        DISCONNECT = "disconnect", "Deconectare cont"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="audit_entries",
    )
    action = models.CharField(max_length=32, choices=Action.choices, db_index=True)
    object_label = models.CharField(max_length=100, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    # Doar metadate, niciodata continut (text OCR, emailuri, transcrieri, tokenuri).
    detail = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Intrare de audit"
        verbose_name_plural = "Intrări de audit"

    def __str__(self):
        return f"{self.get_action_display()} · {self.object_label}#{self.object_id}"
