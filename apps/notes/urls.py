from django.urls import path

from apps.notes import views

app_name = "notes"

urlpatterns = [
    path("", views.NoteListView.as_view(), name="list"),
    path("nou/", views.NoteCreateView.as_view(), name="create"),
    path("<int:pk>/", views.NoteDetailView.as_view(), name="detail"),
    path("<int:pk>/modifica/", views.NoteUpdateView.as_view(), name="update"),
    path("<int:pk>/sterge/", views.delete_note, name="delete"),
    path("<int:pk>/fixeaza/", views.toggle_pin, name="toggle_pin"),
    path("<int:pk>/element/<int:item_pk>/", views.toggle_item, name="toggle_item"),
]
