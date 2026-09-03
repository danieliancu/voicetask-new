from datetime import date

from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from apps.core.mixins import OwnerQuerysetMixin
from apps.core.ratelimit import limited
from apps.daily_brief import services
from apps.daily_brief.models import DailyBrief


class BriefView(OwnerQuerysetMixin, TemplateView):
    template_name = "daily_brief/brief.html"

    def get_queryset(self):
        return None

    def get_day(self) -> date:
        raw = self.kwargs.get("day")
        if raw:
            try:
                return date.fromisoformat(raw)
            except ValueError as exc:
                raise Http404 from exc
        return timezone.localdate()

    def get_context_data(self, **kwargs):
        from apps.core import dates_ro

        context = super().get_context_data(**kwargs)
        day = self.get_day()
        brief = services.get_or_create_brief(self.request.user, day)
        context.update(
            {
                "page": "brief",
                "brief": brief,
                "day": day,
                "greeting": dates_ro.greeting_for(),
                "timeline": brief.snapshot.get("appointments", []),
                "todos": _todos(brief),
                "emails": brief.snapshot.get("emails", []),
                "counts": brief.counts,
                "questions": brief.questions.all()[:10],
                "polish_rejected": brief.polish_rejected_reason,
            }
        )
        return context


def _todos(brief: DailyBrief) -> list[dict]:
    """Elementele „De rezolvat": alarme si documente cu termen apropiat."""
    from apps.core import dates_ro

    items = []
    for reminder in brief.snapshot.get("reminders", []):
        items.append(
            {
                "title": reminder["title"],
                "detail": f"Alarmă la {reminder['time']}",
                "icon": "bell",
                "kind": "alarma",
                "pk": reminder["id"],
            }
        )
    for document in brief.snapshot.get("documents", []):
        # Datele si sumele se afiseaza in format romanesc, nu ISO.
        due = dates_ro.format_date(date.fromisoformat(document["due_date"]))
        detail = f"Scadență {due}"
        if document.get("amount"):
            suma = f"{float(document['amount']):.2f}".replace(".", ",")
            detail += f" · {suma} {document.get('currency', '')}".rstrip()
        items.append(
            {
                "title": document["title"],
                "detail": detail,
                "icon": "scan",
                "kind": "document",
                "pk": document["id"],
            }
        )
    return items


@login_required
def status(request):
    brief = DailyBrief.objects.filter(owner=request.user, date=timezone.localdate()).first()
    return render(request, "daily_brief/_status.html", {"brief": brief})


@login_required
@require_POST
def regenerate(request):
    brief = services.get_or_create_brief(request.user, timezone.localdate(), force=True)
    return render(request, "daily_brief/_player.html", {"brief": brief})


@login_required
def audio(request, pk: int):
    """Audio-ul se serveste prin view, nu prin URL direct de media."""
    brief = get_object_or_404(DailyBrief.objects.for_user(request.user), pk=pk)
    if not brief.audio_file:
        raise Http404
    content_type = "audio/mpeg" if brief.audio_file.name.endswith(".mp3") else "audio/wav"
    return FileResponse(brief.audio_file.open("rb"), content_type=content_type)


@login_required
@require_POST
@limited("ai")
def ask(request):
    """„Întreabă despre ziua mea" — raspuns construit din instantaneul zilei."""
    question = request.POST.get("intrebare", "").strip()
    if not question:
        return render(request, "daily_brief/_qa_item.html", {"error": "Scrie o întrebare."})
    brief = services.get_or_create_brief(request.user, timezone.localdate())
    answer = services.ask(request.user, brief, question)
    return render(request, "daily_brief/_qa_item.html", {"item": answer})
