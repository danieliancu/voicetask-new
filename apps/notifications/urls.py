from django.urls import path

from apps.notifications import views

app_name = "notifications"

urlpatterns = [
    path("", views.NotificationListView.as_view(), name="inbox"),
    path("<int:pk>/citit/", views.mark_read, name="mark_read"),
    path("citeste-tot/", views.mark_all_read, name="mark_all_read"),
    path("abonare/", views.subscribe, name="subscribe"),
    path("dezabonare/", views.unsubscribe, name="unsubscribe"),
    path("stare/", views.status, name="status"),
]
