from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView

from apps.core.mixins import OwnerFormMixin, OwnerQuerysetMixin
from apps.core.models import AuditLog
from apps.scheduling import calendars, services
from apps.scheduling.forms import AppointmentForm, ReminderForm
from apps.scheduling.models import Appointment, Reminder

VALID_VIEWS = {"zi", "saptamana", "luna"}


def _selected_day(request) -> date:
    raw = request.GET.get("d", "")
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return timezone.localdate()


def _selected_view(request) -> str:
    view = request.GET.get("vizualizare", "zi")
    return view if view in VALID_VIEWS else "zi"


class CalendarView(OwnerQuerysetMixin, TemplateView):
    template_name = "scheduling/calendar.html"

    def get_queryset(self):
        return None

    def get_context_data(self, **kwargs):
        from apps.daily_brief.models import DailyBrief

        context = super().get_context_data(**kwargs)
        day = _selected_day(self.request)
        view = _selected_view(self.request)
        calendar_context = calendars.build(self.request.user, view=view, day=day)
        context.update(
            {
                "page": "scheduling",
                "cal": calendar_context,
                "views": calendars.VIEWS,
                "brief": DailyBrief.objects.filter(
                    owner=self.request.user, date=timezone.localdate()
                ).first(),
                "upcoming_reminders": Reminder.objects.for_user(self.request.user)
                .filter(status=Reminder.Status.SCHEDULED, remind_at__gte=timezone.now())
                .order_by("remind_at")[:4],
            }
        )
        return context


@login_required
def agenda_partial(request):
    day = _selected_day(request)
    view = _selected_view(request)
    calendar_context = calendars.build(request.user, view=view, day=day)
    # Acelasi fragment ca in pagina completa: selectorul si agenda se schimba
    # impreuna, deci optiunea activa nu poate ramane in urma fata de continut.
    return render(
        request,
        "scheduling/_calendar_body.html",
        {"cal": calendar_context, "views": calendars.VIEWS},
    )


class AppointmentDetailView(OwnerQuerysetMixin, DetailView):
    model = Appointment
    template_name = "scheduling/appointment_detail.html"
    context_object_name = "appointment"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page"] = "scheduling"
        return context


class AppointmentFormMixin(OwnerQuerysetMixin, OwnerFormMixin):
    model = Appointment
    form_class = AppointmentForm
    template_name = "scheduling/appointment_form.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page"] = "scheduling"
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        services.sync_appointment_reminder(
            self.object, form.cleaned_data.get("reminder_offset")
        )
        messages.success(self.request, "Programarea a fost salvată.")
        return response


class AppointmentCreateView(AppointmentFormMixin, CreateView):
    def get_initial(self):
        initial = super().get_initial()
        day = _selected_day(self.request)
        initial["starts_at"] = timezone.localtime(
            timezone.now().replace(minute=0, second=0, microsecond=0)
        ).replace(year=day.year, month=day.month, day=day.day)
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Programare nouă"
        return context


class AppointmentUpdateView(AppointmentFormMixin, UpdateView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Modifică programarea"
        return context


@login_required
def delete_appointment(request, pk: int):
    appointment = get_object_or_404(Appointment.objects.for_user(request.user), pk=pk)
    if request.method != "POST":
        return render(
            request,
            "core/_confirm_delete.html",
            {
                "objects": [{"kind": "programare", "pk": pk, "title": appointment.title}],
                "retention_days": _retention_days(),
                "action_url": reverse("scheduling:delete", args=[pk]),
                "external_warning": appointment.is_external,
            },
        )
    appointment.delete()
    AuditLog.objects.create(
        user=request.user,
        action=AuditLog.Action.DELETE,
        object_label=Appointment._meta.label,
        object_id=str(pk),
    )
    messages.success(
        request,
        f"Programarea a fost mutată în coș. O poți recupera timp de {_retention_days()} de zile.",
    )
    if getattr(request, "htmx", False):
        response = HttpResponse(status=204)
        response["HX-Redirect"] = reverse("scheduling:calendar")
        return response
    return redirect("scheduling:calendar")


class ReminderListView(OwnerQuerysetMixin, ListView):
    model = Reminder
    template_name = "scheduling/reminder_list.html"
    context_object_name = "reminders"
    paginate_by = 30

    def get_queryset(self):
        return super().get_queryset().select_related("appointment").order_by("remind_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page"] = "scheduling"
        return context


class ReminderDetailView(OwnerQuerysetMixin, DetailView):
    model = Reminder
    template_name = "scheduling/reminder_detail.html"
    context_object_name = "reminder"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page"] = "scheduling"
        return context


class ReminderFormMixin(OwnerQuerysetMixin, OwnerFormMixin):
    model = Reminder
    form_class = ReminderForm
    template_name = "scheduling/reminder_form.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page"] = "scheduling"
        return context

    def form_valid(self, form):
        messages.success(self.request, "Alarma a fost salvată.")
        return super().form_valid(form)


class ReminderCreateView(ReminderFormMixin, CreateView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Alarmă nouă"
        return context


class ReminderUpdateView(ReminderFormMixin, UpdateView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Modifică alarma"
        return context


@login_required
@require_POST
def snooze_reminder(request, pk: int):
    reminder = get_object_or_404(Reminder.objects.for_user(request.user), pk=pk)
    minutes = int(request.POST.get("minute", 10) or 10)
    reminder.snooze(minutes)
    return render(request, "scheduling/_reminder_row.html", {"reminder": reminder})


@login_required
@require_POST
def complete_reminder(request, pk: int):
    reminder = get_object_or_404(Reminder.objects.for_user(request.user), pk=pk)
    reminder.status = Reminder.Status.DONE
    reminder.save(update_fields=["status", "updated_at"])
    return render(request, "scheduling/_reminder_row.html", {"reminder": reminder})


@login_required
@require_POST
def push_to_calendar(request, pk: int):
    """Scrie programarea in calendarul extern. Numai dupa confirmare explicita."""
    appointment = get_object_or_404(Appointment.objects.for_user(request.user), pk=pk)
    if request.POST.get("confirm") != "da":
        return render(
            request,
            "scheduling/_sync_state.html",
            {"appointment": appointment, "needs_confirm": True},
        )
    from apps.integrations.sync import push_appointment

    result = push_appointment(request.user, appointment)
    return render(
        request,
        "scheduling/_sync_state.html",
        {"appointment": appointment, "result": result},
    )


def _retention_days() -> int:
    from django.conf import settings

    return settings.TRASH_RETENTION_DAYS
