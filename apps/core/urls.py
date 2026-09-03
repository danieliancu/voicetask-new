from django.urls import path

from apps.core import views

app_name = "core"

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("agenda-apropiata/", views.today_summary, name="upcoming_partial"),
    path("modifica/", views.EditHubView.as_view(), name="edit_hub"),
    path("modifica/<slug:kind>/<int:pk>/", views.edit_dispatch, name="edit_item"),
    path("sterge/", views.DeleteHubView.as_view(), name="delete_hub"),
    path("sterge/confirma/", views.delete_confirm, name="delete_confirm"),
    path("sterge/executa/", views.delete_execute, name="delete_execute"),
    path("cos/", views.TrashView.as_view(), name="trash"),
    path("cos/restaureaza/", views.trash_restore, name="trash_restore"),
    path("offline/", views.OfflineView.as_view(), name="offline"),
]
