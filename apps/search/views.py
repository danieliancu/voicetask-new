from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from apps.core.mixins import OwnerQuerysetMixin
from apps.core.ratelimit import limited
from apps.search import service
from apps.search.models import RecentSearch

MIN_QUERY_LENGTH = 2


class SearchIndexView(OwnerQuerysetMixin, TemplateView):
    template_name = "search/index.html"

    def get_queryset(self):
        return None

    def get_context_data(self, **kwargs):
        from apps.daily_brief.models import DailyBrief

        context = super().get_context_data(**kwargs)
        query = self.request.GET.get("q", "").strip()
        brief = DailyBrief.objects.filter(
            owner=self.request.user, date=timezone.localdate()
        ).first()
        context.update(
            {
                "page": "search",
                "query": query,
                "filters": service.source_filters(),
                "selected_sources": self.request.GET.getlist("sursa"),
                "sort": self.request.GET.get("sortare", "relevanta"),
                "sort_choices": service.SORT_CHOICES,
                "recent": RecentSearch.objects.for_user(self.request.user)[:8],
                "brief": brief,
                "brief_highlights": _brief_highlights(brief),
            }
        )
        if query:
            context["results"] = _run(self.request, query)
        return context


def _brief_highlights(brief) -> list[dict]:
    """Secțiunea „Din rezumatul de azi": primele elemente din instantaneu."""
    from datetime import date

    from apps.core import dates_ro

    if brief is None or not brief.snapshot:
        return []
    highlights = []
    for item in brief.snapshot.get("appointments", [])[:2]:
        highlights.append(
            {"title": item["title"], "detail": f"ora {item['time']}", "kind": "programare"}
        )
    for item in brief.snapshot.get("documents", [])[:1]:
        due = dates_ro.format_date(date.fromisoformat(item["due_date"]))
        highlights.append(
            {"title": item["title"], "detail": f"termen {due}", "kind": "document"}
        )
    return highlights


def _run(request, query: str):
    sources = [key for key in request.GET.getlist("sursa") if key]
    sort = request.GET.get("sortare", "relevanta")
    return service.search(request.user, query, sources=sources or None, sort=sort)


@login_required
@limited("search")
def results(request):
    query = request.GET.get("q", "").strip()
    if len(query) < MIN_QUERY_LENGTH:
        return render(request, "search/_results.html", {"results": None, "query": query})
    found = _run(request, query)
    RecentSearch.record(request.user, query)
    return render(request, "search/_results.html", {"results": found, "query": query})


@login_required
def recent(request):
    return render(
        request,
        "search/_recent.html",
        {"recent": RecentSearch.objects.for_user(request.user)[:8]},
    )


@login_required
@require_POST
def clear_recent(request):
    RecentSearch.objects.for_user(request.user).delete()
    return render(request, "search/_recent.html", {"recent": []})
