from django.urls import path

from apps.daily_brief import views

app_name = "daily_brief"

urlpatterns = [
    path("", views.BriefView.as_view(), name="today"),
    path("stare/", views.status, name="status"),
    path("regenereaza/", views.regenerate, name="regenerate"),
    path("intreaba/", views.ask, name="ask"),
    path("audio/<int:pk>/", views.audio, name="audio"),
    path("<slug:day>/", views.BriefView.as_view(), name="by_date"),
]
