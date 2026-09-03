from django.urls import path

from apps.assistant import views

app_name = "assistant"

urlpatterns = [
    path("inregistreaza/", views.CaptureView.as_view(), name="capture"),
    path("voce/", views.voice_upload, name="voice_upload"),
    path("text/", views.text_command, name="text_command"),
    path("schita/<uuid:uid>/", views.draft_detail, name="draft"),
    path("schita/<uuid:uid>/clarifica/", views.draft_clarify, name="draft_clarify"),
    path("schita/<uuid:uid>/confirma/", views.draft_confirm, name="draft_confirm"),
    path("schita/<uuid:uid>/renunta/", views.draft_discard, name="draft_discard"),
    path("modifica/<slug:kind>/<int:pk>/", views.EditByVoiceView.as_view(), name="edit"),
    path("modifica/<slug:kind>/<int:pk>/voce/", views.edit_by_voice, name="edit_by_voice"),
]
