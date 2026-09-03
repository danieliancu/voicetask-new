from django.urls import reverse

from apps.core import dates_ro
from apps.core.enums import ItemKind
from apps.integrations.models import EmailReference
from apps.search.registry import SearchHit, SearchSource, register


class EmailSource(SearchSource):
    key = "emailuri"
    label = "Emailuri"
    icon = "mail"
    search_fields = ("subject", "sender", "snippet")

    def queryset(self, user):
        return EmailReference.objects.for_user(user)

    def order_field(self) -> str:
        return "-received_at"

    def to_hit(self, obj: EmailReference, *, score: float = 0.0) -> SearchHit:
        when = obj.follow_up_at or obj.received_at
        return SearchHit(
            kind=ItemKind.EMAIL,
            pk=obj.pk,
            title=(
                f"Urmărește email: {obj.sender_name}"
                if obj.status == EmailReference.Status.FOLLOW_UP
                else obj.subject or obj.sender_name
            ),
            subtitle=(
                f"{dates_ro.relative_day_label(when)} • {dates_ro.format_time(when)}"
                if when
                else obj.snippet
            ),
            source_label="Gmail",
            source_icon="mail",
            color_token=obj.color_token,
            url=reverse("integrations:email_detail", args=[obj.pk]),
            when=when,
            tab_label=dates_ro.short_tab_label(when),
            score=score,
        )


register(EmailSource())
