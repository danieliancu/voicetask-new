from django.urls import path

from apps.search import views

app_name = "search"

urlpatterns = [
    path("", views.SearchIndexView.as_view(), name="index"),
    path("rezultate/", views.results, name="results"),
    path("recente/", views.recent, name="recent"),
    path("recente/sterge/", views.clear_recent, name="clear_recent"),
]
