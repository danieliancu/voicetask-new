"""Preferintele si starea navigatiei, disponibile in toate sabloanele."""

from apps.accounts.models import UserPreference


def user_context(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"prefs": None, "unread_count": 0}
    from apps.notifications.models import Notification

    return {
        "prefs": UserPreference.for_user(user),
        "unread_count": Notification.objects.for_user(user).filter(read_at__isnull=True).count(),
    }
