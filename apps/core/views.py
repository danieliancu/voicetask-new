"""Ecranele Acasă, Modifică, Șterge, Coș, plus service worker si manifest."""

from __future__ import annotations

from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from apps.core import dates_ro
from apps.core.enums import ItemKind
from apps.core.mixins import OwnerQuerysetMixin
from apps.core.models import AuditLog
from apps.core.registry import KIND_TO_MODEL, model_for_kind

UPCOMING_LIMIT = 8


def upcoming_items(user, *, limit: int = UPCOMING_LIMIT, days: int = 30) -> list:
    """Urmatoarele elemente din agenda, indiferent de tip, sortate cronologic."""
    from apps.documents.models import ScannedDocument
    from apps.integrations.models import EmailReference
    from apps.scheduling.models import Appointment, Reminder

    now = timezone.now()
    horizon = now + timedelta(days=days)
    entries: list[dict] = []

    for appointment in Appointment.objects.for_user(user).filter(
        starts_at__gte=now - timedelta(hours=2), starts_at__lte=horizon
    )[:limit]:
        entries.append(
            {
                "kind": ItemKind.APPOINTMENT,
                "pk": appointment.pk,
                "title": appointment.title,
                "when": appointment.starts_at,
                "end": appointment.ends_at,
                "location": appointment.location,
                "icon": appointment.icon,
                "color": appointment.color_token,
                "url": appointment.get_absolute_url(),
                "source_label": "Google Calendar" if appointment.is_external else "Programare",
                "reminder": appointment.reminders.filter(
                    status="scheduled"
                ).order_by("remind_at").first(),
            }
        )

    for reminder in (
        Reminder.objects.for_user(user)
        .filter(remind_at__gte=now - timedelta(hours=2), remind_at__lte=horizon)
        .exclude(status="done")
        .select_related("appointment", "email_reference")[:limit]
    ):
        if reminder.appointment_id:
            continue
        entries.append(
            {
                "kind": ItemKind.REMINDER,
                "pk": reminder.pk,
                "title": reminder.title,
                "when": reminder.remind_at,
                "end": None,
                "location": "",
                "icon": "bell",
                "color": reminder.color_token,
                "url": reminder.get_absolute_url(),
                "source_label": "Alarmă",
                "reminder": reminder,
            }
        )

    for email in EmailReference.objects.for_user(user).filter(
        status=EmailReference.Status.FOLLOW_UP, follow_up_at__lte=horizon
    )[:limit]:
        entries.append(
            {
                "kind": ItemKind.EMAIL,
                "pk": email.pk,
                "title": f"Urmărește email: {email.sender_name}",
                "when": email.follow_up_at or email.received_at,
                "end": None,
                "location": "",
                "icon": "mail",
                "color": email.color_token,
                "url": reverse("integrations:email_detail", args=[email.pk]),
                "source_label": "Gmail",
                "reminder": None,
            }
        )

    for document in ScannedDocument.objects.for_user(user).filter(
        processing_status__in=[ScannedDocument.Status.READY, ScannedDocument.Status.CONFIRMED]
    )[:limit]:
        due = document.field("due_date")
        if not due:
            continue
        try:
            from datetime import date as date_cls

            due_date = date_cls.fromisoformat(str(due))
        except (TypeError, ValueError):
            continue
        entries.append(
            {
                "kind": ItemKind.DOCUMENT,
                "pk": document.pk,
                "title": str(document),
                # Un termen de plata este o zi, nu un moment: nu afisam ora.
                "all_day": True,
                "when": timezone.make_aware(
                    timezone.datetime.combine(due_date, timezone.datetime.min.time()),
                    timezone.get_current_timezone(),
                ),
                "end": None,
                "location": "",
                "icon": "scan",
                "color": document.color_token,
                "url": document.get_absolute_url(),
                "source_label": "Document scanat",
                "reminder": None,
            }
        )

    entries.sort(key=lambda item: item["when"])
    for entry in entries:
        entry["tab_label"] = dates_ro.short_tab_label(entry["when"])
    return entries[:limit]


class HomeView(OwnerQuerysetMixin, TemplateView):
    template_name = "core/home.html"

    def get_queryset(self):  # HomeView nu are model propriu
        return None

    def get_context_data(self, **kwargs):
        from apps.daily_brief import services as brief_services
        from apps.integrations.models import ConnectedAccount

        context = super().get_context_data(**kwargs)
        user = self.request.user
        today = timezone.localdate()
        # Folosim acelasi flux ca ecranul rezumatului: daca un element nou a
        # invalidat snapshot-ul, acesta este reconstruit; daca nu s-a schimbat
        # nimic, rezumatul existent este returnat din cache.
        brief = brief_services.get_or_create_brief(user, today)
        accounts = {
            account.provider: account for account in ConnectedAccount.objects.for_user(user)
        }
        counts = brief.counts
        context.update(
            {
                "page": "home",
                "upcoming": upcoming_items(user),
                "brief": brief,
                "brief_counts": counts,
                # Cardul afiseaza doar programari si lucruri importante. Butonul
                # de redare trebuie sa urmeze aceleasi contoare vizibile.
                "brief_has_content": bool(
                    counts.get("appointments", 0) or counts.get("todo", 0)
                ),
                "gmail_account": accounts.get(ConnectedAccount.Provider.GMAIL),
                "calendar_account": accounts.get(ConnectedAccount.Provider.CALENDAR),
            }
        )
        return context


@login_required
def today_summary(request):
    """Fragment reimprospatat periodic pe ecranul Acasă."""
    return render(
        request,
        "core/_upcoming_list.html",
        {"upcoming": upcoming_items(request.user)},
    )


class EditHubView(OwnerQuerysetMixin, TemplateView):
    """Ecranul „Modifică": alege obiectul, apoi treci la formularul aplicatiei lui."""

    template_name = "core/edit_hub.html"

    def get_queryset(self):
        return None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page": "edit",
                "items": upcoming_items(self.request.user, limit=30, days=120),
                "kinds": KIND_TO_MODEL.keys(),
            }
        )
        return context


@login_required
def edit_dispatch(request, kind: str, pk: int):
    """Trimite la formularul de editare al aplicatiei care detine obiectul."""
    routes = {
        ItemKind.NOTE: "notes:update",
        ItemKind.APPOINTMENT: "scheduling:update",
        ItemKind.REMINDER: "scheduling:reminder_update",
        ItemKind.DOCUMENT: "documents:detail",
        ItemKind.EMAIL: "integrations:email_detail",
    }
    route = routes.get(kind)
    if route is None:
        messages.error(request, "Tip de element necunoscut.")
        return redirect("core:edit_hub")
    model = model_for_kind(kind)
    if not model.objects.filter(pk=pk, owner=request.user).exists():
        from django.http import Http404

        raise Http404
    return redirect(route, pk=pk)


DELETE_FILTERS = (
    ("toate", "Toate", ""),
    ("evenimente", "Evenimente", ItemKind.APPOINTMENT),
    ("mementouri", "Mementouri", ItemKind.REMINDER),
    ("documente", "Documente", ItemKind.DOCUMENT),
    ("notite", "Notițe", ItemKind.NOTE),
)


def _deletable_items(user, kind_filter: str = "") -> list:
    items = upcoming_items(user, limit=200, days=365)
    from apps.notes.models import Note

    for note in Note.objects.for_user(user)[:50]:
        items.append(
            {
                "kind": ItemKind.NOTE,
                "pk": note.pk,
                "title": note.title,
                "when": note.updated_at,
                "end": None,
                "location": "",
                "icon": "note",
                "color": note.color_token,
                "url": note.get_absolute_url(),
                "source_label": "Notiță",
                "reminder": None,
                "tab_label": "NOTIȚE",
            }
        )
    if kind_filter:
        items = [item for item in items if item["kind"] == kind_filter]
    return items


class DeleteHubView(OwnerQuerysetMixin, TemplateView):
    template_name = "core/delete_hub.html"

    def get_queryset(self):
        return None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        selected = self.request.GET.get("tip", "") or "toate"
        kind_by_key = {key: kind for key, _, kind in DELETE_FILTERS}
        all_items = _deletable_items(self.request.user)
        kind = kind_by_key.get(selected, "")
        items = [item for item in all_items if not kind or item["kind"] == kind]
        filters = [
            {
                "key": key,
                "label": label,
                "count": len(all_items)
                if not filter_kind
                else sum(1 for item in all_items if item["kind"] == filter_kind),
                "is_selected": key == selected,
            }
            for key, label, filter_kind in DELETE_FILTERS
        ]
        context.update(
            {
                "page": "delete",
                "items": items,
                "filters": filters,
                "selected_filter": selected,
                "retention_days": _retention_days(),
            }
        )
        return context


def _retention_days() -> int:
    from django.conf import settings

    return settings.TRASH_RETENTION_DAYS


def _parse_selection(request) -> list[tuple[str, int]]:
    """Valorile din formular au forma „tip:pk"."""
    selection = []
    for raw in request.POST.getlist("element"):
        kind, _, pk = raw.partition(":")
        if kind in KIND_TO_MODEL and pk.isdigit():
            selection.append((kind, int(pk)))
    return selection


@login_required
@require_POST
def delete_confirm(request):
    """Pasul obligatoriu de confirmare. Nicio stergere nu ocoleste acest ecran."""
    selection = _parse_selection(request)
    objects = []
    for kind, pk in selection:
        model = model_for_kind(kind)
        obj = model.objects.filter(pk=pk, owner=request.user).first()
        if obj is not None:
            objects.append({"kind": kind, "pk": pk, "title": str(obj)})
    return render(
        request,
        "core/_confirm_delete.html",
        {
            "objects": objects,
            "retention_days": _retention_days(),
            "action_url": reverse("core:delete_execute"),
        },
    )


@login_required
@require_POST
def delete_execute(request):
    selection = _parse_selection(request)
    deleted = 0
    with transaction.atomic():
        for kind, pk in selection:
            model = model_for_kind(kind)
            obj = model.objects.filter(pk=pk, owner=request.user).first()
            if obj is None:
                continue
            obj.delete()
            AuditLog.objects.create(
                user=request.user,
                action=AuditLog.Action.DELETE,
                object_label=model._meta.label,
                object_id=str(pk),
            )
            deleted += 1
    if deleted:
        messages.success(
            request,
            f"{deleted} element(e) mutate în coș. Le poți recupera timp de "
            f"{_retention_days()} de zile.",
        )
    else:
        messages.info(request, "Nu a fost selectat niciun element.")
    return redirect("core:trash")


class TrashView(OwnerQuerysetMixin, TemplateView):
    template_name = "core/trash.html"

    def get_queryset(self):
        return None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        entries = []
        for kind in KIND_TO_MODEL:
            model = model_for_kind(kind)
            for obj in model.all_objects.filter(
                owner=self.request.user, deleted_at__isnull=False
            ).order_by("-deleted_at")[:50]:
                entries.append(
                    {
                        "kind": kind,
                        "pk": obj.pk,
                        "title": str(obj),
                        "deleted_at": obj.deleted_at,
                        "expires_at": obj.deleted_at + timedelta(days=_retention_days()),
                    }
                )
        entries.sort(key=lambda item: item["deleted_at"], reverse=True)
        context.update(
            {"page": "trash", "entries": entries, "retention_days": _retention_days()}
        )
        return context


@login_required
@require_POST
def trash_restore(request):
    restored = 0
    for kind, pk in _parse_selection(request):
        model = model_for_kind(kind)
        obj = model.all_objects.filter(pk=pk, owner=request.user).first()
        if obj is None or not obj.is_deleted:
            continue
        obj.restore()
        AuditLog.objects.create(
            user=request.user,
            action=AuditLog.Action.RESTORE,
            object_label=model._meta.label,
            object_id=str(pk),
        )
        restored += 1
    messages.success(request, f"{restored} element(e) restaurate.")
    return redirect("core:trash")


class ServiceWorkerView(TemplateView):
    """Servit din radacina, ca scope-ul sa fie „/"."""

    template_name = "core/sw.js"
    content_type = "application/javascript"

    def render_to_response(self, context, **response_kwargs):
        response = super().render_to_response(context, **response_kwargs)
        response["Service-Worker-Allowed"] = "/"
        response["Cache-Control"] = "no-cache"
        return response

    def get_context_data(self, **kwargs):
        from django.conf import settings

        context = super().get_context_data(**kwargs)
        context["cache_version"] = settings.SW_CACHE_VERSION
        return context


class ManifestView(TemplateView):
    template_name = "core/manifest.webmanifest"
    content_type = "application/manifest+json"


class OfflineView(TemplateView):
    template_name = "core/offline.html"


def error_403(request, exception=None):
    return render(request, "core/403.html", status=403)


def error_404(request, exception=None):
    return render(request, "core/404.html", status=404)


def error_500(request):
    return render(request, "core/500.html", status=500)
