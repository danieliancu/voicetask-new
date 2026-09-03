from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from apps.core.mixins import HtmxPartialMixin, OwnerFormMixin, OwnerQuerysetMixin
from apps.core.models import AuditLog
from apps.notes.forms import NoteForm
from apps.notes.models import ChecklistItem, Note, NoteCategory
from apps.search.normalize import normalize


class NoteListView(OwnerQuerysetMixin, HtmxPartialMixin, ListView):
    model = Note
    template_name = "notes/note_list.html"
    partial_template_name = "notes/_note_list.html"
    context_object_name = "notes"
    paginate_by = 25

    def get_queryset(self):
        queryset = super().get_queryset().select_related("category").prefetch_related("items")
        category = self.request.GET.get("categorie", "")
        if category == "documente":
            queryset = queryset.filter(source="scan")
        elif category:
            queryset = queryset.filter(category__slug=category)
        query = self.request.GET.get("q", "").strip()
        if query:
            queryset = queryset.filter(match_text__contains=normalize(query))
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        notes = context["notes"]
        context.update(
            {
                "page": "notes",
                "categories": NoteCategory.objects.for_user(self.request.user),
                "selected_category": self.request.GET.get("categorie", ""),
                "query": self.request.GET.get("q", ""),
                "pinned": [note for note in notes if note.is_pinned],
                "unpinned": [note for note in notes if not note.is_pinned],
            }
        )
        return context


class NoteDetailView(OwnerQuerysetMixin, DetailView):
    model = Note
    template_name = "notes/note_detail.html"
    context_object_name = "note"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page"] = "notes"
        return context


class NoteCreateView(OwnerQuerysetMixin, OwnerFormMixin, CreateView):
    model = Note
    form_class = NoteForm
    template_name = "notes/note_form.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({"page": "notes", "title": "Notiță nouă"})
        return context

    def form_valid(self, form):
        messages.success(self.request, "Notița a fost salvată.")
        return super().form_valid(form)


class NoteUpdateView(OwnerQuerysetMixin, OwnerFormMixin, UpdateView):
    model = Note
    form_class = NoteForm
    template_name = "notes/note_form.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({"page": "notes", "title": "Modifică notița"})
        return context

    def form_valid(self, form):
        messages.success(self.request, "Modificările au fost salvate.")
        return super().form_valid(form)


@login_required
@require_POST
def toggle_pin(request, pk: int):
    note = get_object_or_404(Note.objects.for_user(request.user), pk=pk)
    note.is_pinned = not note.is_pinned
    note.save(update_fields=["is_pinned", "updated_at"])
    return render(request, "notes/_note_card.html", {"note": note})


@login_required
@require_POST
def toggle_item(request, pk: int, item_pk: int):
    note = get_object_or_404(Note.objects.for_user(request.user), pk=pk)
    item = get_object_or_404(ChecklistItem.objects.filter(note=note), pk=item_pk)
    item.is_done = not item.is_done
    item.save(update_fields=["is_done", "updated_at"])
    return render(request, "notes/_checklist_item.html", {"item": item, "note": note})


@login_required
def delete_note(request, pk: int):
    """GET arata dialogul de confirmare; numai POST sterge."""
    note = get_object_or_404(Note.objects.for_user(request.user), pk=pk)
    if request.method != "POST":
        return render(
            request,
            "core/_confirm_delete.html",
            {
                "objects": [{"kind": "notita", "pk": note.pk, "title": note.title}],
                "retention_days": _retention_days(),
                "action_url": reverse("notes:delete", args=[note.pk]),
            },
        )
    note.delete()
    AuditLog.objects.create(
        user=request.user,
        action=AuditLog.Action.DELETE,
        object_label=Note._meta.label,
        object_id=str(note.pk),
    )
    messages.success(
        request,
        f"Notița a fost mutată în coș. O poți recupera timp de {_retention_days()} de zile.",
    )
    if getattr(request, "htmx", False):
        response = HttpResponse(status=204)
        response["HX-Redirect"] = reverse("notes:list")
        return response
    return redirect("notes:list")


def _retention_days() -> int:
    from django.conf import settings

    return settings.TRASH_RETENTION_DAYS
