import json

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import ListView

from apps.core.mixins import OwnerQuerysetMixin
from apps.notifications import dispatch
from apps.notifications.models import Notification, PushSubscription


class NotificationListView(OwnerQuerysetMixin, ListView):
    model = Notification
    template_name = "notifications/inbox.html"
    context_object_name = "notifications"
    paginate_by = 30

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page": "notifications",
                "push": dispatch.push_status(self.request.user),
                "vapid_public_key": settings.VAPID_PUBLIC_KEY,
            }
        )
        return context


@login_required
@require_POST
def mark_read(request, pk: int):
    notification = get_object_or_404(Notification.objects.for_user(request.user), pk=pk)
    if notification.read_at is None:
        notification.read_at = timezone.now()
        notification.save(update_fields=["read_at", "updated_at"])
    return render(request, "notifications/_notification_row.html", {"notification": notification})


@login_required
@require_POST
def mark_all_read(request):
    Notification.objects.for_user(request.user).filter(read_at__isnull=True).update(
        read_at=timezone.now()
    )
    return render(
        request,
        "notifications/_list.html",
        {"notifications": Notification.objects.for_user(request.user)[:30]},
    )


@login_required
@require_POST
def subscribe(request):
    """Inregistreaza un abonament Web Push trimis de service worker."""
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"eroare": "Date invalide."}, status=400)

    endpoint = payload.get("endpoint", "")
    keys = payload.get("keys") or {}
    if not endpoint or not keys.get("p256dh") or not keys.get("auth"):
        return JsonResponse({"eroare": "Abonament incomplet."}, status=400)

    PushSubscription.objects.update_or_create(
        owner=request.user,
        endpoint=endpoint[:500],
        defaults={
            "p256dh": keys["p256dh"][:200],
            "auth": keys["auth"][:100],
            "user_agent": request.META.get("HTTP_USER_AGENT", "")[:200],
            "is_active": True,
            "failure_count": 0,
        },
    )
    return JsonResponse(dispatch.push_status(request.user))


@login_required
@require_POST
def unsubscribe(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}
    endpoint = payload.get("endpoint", "")
    queryset = PushSubscription.objects.for_user(request.user)
    if endpoint:
        queryset = queryset.filter(endpoint=endpoint)
    queryset.update(is_active=False)
    return JsonResponse(dispatch.push_status(request.user))


@login_required
def status(request):
    return JsonResponse(dispatch.push_status(request.user))
