"""Descoperirea modelelor cu soft delete si maparea lor la tipurile din interfata."""

from __future__ import annotations

from django.apps import apps as django_apps

from apps.core.enums import ItemKind

#: Tipul din URL -> "app_label.ModelName". Sursa unica pentru ecranele Modifică / Șterge.
KIND_TO_MODEL: dict[str, str] = {
    ItemKind.NOTE: "notes.Note",
    ItemKind.APPOINTMENT: "scheduling.Appointment",
    ItemKind.REMINDER: "scheduling.Reminder",
    ItemKind.DOCUMENT: "documents.ScannedDocument",
    ItemKind.EMAIL: "integrations.EmailReference",
}


def soft_delete_models() -> list[type]:
    from apps.core.models import SoftDeleteModel

    return [
        model
        for model in django_apps.get_models()
        if issubclass(model, SoftDeleteModel) and not model._meta.abstract
    ]


def model_for_kind(kind: str):
    label = KIND_TO_MODEL.get(kind)
    if label is None:
        return None
    return django_apps.get_model(label)


def kind_for_model(model) -> str | None:
    label = f"{model._meta.app_label}.{model._meta.object_name}"
    for kind, mapped in KIND_TO_MODEL.items():
        if mapped == label:
            return kind
    return None
