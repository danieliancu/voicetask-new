from django.urls import reverse

from apps.core import dates_ro
from apps.core.enums import ItemKind
from apps.documents.models import ScannedDocument
from apps.search.registry import SearchHit, SearchSource, register


class DocumentSource(SearchSource):
    key = "documente"
    label = "Documente"
    icon = "scan"
    search_fields = ("title", "extracted_text")

    def queryset(self, user):
        return ScannedDocument.objects.for_user(user).exclude(
            processing_status=ScannedDocument.Status.FAILED
        )

    def to_hit(self, obj: ScannedDocument, *, score: float = 0.0) -> SearchHit:
        parts = []
        amount = obj.field("amount")
        if amount:
            currency = obj.field("currency") or ""
            suma = f"{float(amount):.2f}".replace(".", ",")
            parts.append(f"Total {suma} {currency}".strip())
        due = obj.field("due_date")
        if due:
            parts.append(f"Scadență {dates_ro.format_date(_as_date(due))}")
        return SearchHit(
            kind=ItemKind.DOCUMENT,
            pk=obj.pk,
            title=str(obj),
            subtitle=" • ".join(parts) or obj.get_document_type_display(),
            source_label="Document scanat",
            source_icon="scan",
            color_token=obj.color_token,
            url=reverse("documents:detail", args=[obj.pk]),
            when=obj.created_at,
            tab_label="DOCUMENT",
            score=score,
        )


def _as_date(value):
    from datetime import date

    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


register(DocumentSource())
