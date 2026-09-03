from django.urls import path

from apps.integrations import views

app_name = "integrations"

urlpatterns = [
    path("", views.IntegrationStatusView.as_view(), name="status"),
    path("google/conecteaza/<slug:provider>/", views.connect, name="connect"),
    path("google/demonstrativ/<slug:provider>/", views.enable_demo, name="enable_demo"),
    path("google/callback/", views.callback, name="callback"),
    path("<int:pk>/deconecteaza/", views.disconnect, name="disconnect"),
    path("<int:pk>/sincronizeaza/", views.sync_now, name="sync"),
    path("emailuri/", views.EmailListView.as_view(), name="email_list"),
    path("emailuri/<int:pk>/", views.EmailDetailView.as_view(), name="email_detail"),
    path("emailuri/<int:pk>/urmareste/", views.toggle_follow_up, name="toggle_follow_up"),
]
