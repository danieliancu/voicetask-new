from django.urls import path

from apps.documents import views

app_name = "documents"

urlpatterns = [
    path("", views.DocumentListView.as_view(), name="list"),
    path("scaneaza/", views.ScanView.as_view(), name="scan"),
    path("incarca/", views.upload, name="upload"),
    path("detecteaza/", views.detect, name="detect"),
    path("<int:pk>/", views.DocumentDetailView.as_view(), name="detail"),
    path("<int:pk>/stare/", views.status, name="status"),
    path("<int:pk>/reproceseaza/", views.reprocess, name="reprocess"),
    path("<int:pk>/confirma/", views.confirm, name="confirm"),
    path("<int:pk>/fotografie/", views.original_image, name="original_image"),
    path("<int:pk>/sterge/", views.delete_document, name="delete"),
]
