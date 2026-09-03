from django.urls import reverse

from apps.core.enums import ItemKind
from apps.notes.models import Note
from apps.search.registry import SearchHit, SearchSource, register


class NoteSource(SearchSource):
    key = "notite"
    label = "Notițe"
    icon = "note"
    search_fields = ("title", "content")

    def queryset(self, user):
        return Note.objects.for_user(user).select_related("category")

    def order_field(self) -> str:
        return "-updated_at"

    def to_hit(self, obj: Note, *, score: float = 0.0) -> SearchHit:
        return SearchHit(
            kind=ItemKind.NOTE,
            pk=obj.pk,
            title=obj.title,
            subtitle=obj.preview,
            source_label="Notiță" if obj.source != "scan" else "Notiță din document",
            source_icon="note",
            color_token=obj.color_token,
            url=reverse("notes:detail", args=[obj.pk]),
            when=obj.updated_at,
            tab_label="NOTIȚE",
            score=score,
            extra={"category": obj.category.name if obj.category else ""},
        )


register(NoteSource())
