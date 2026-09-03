from django.urls import path

from apps.accounts import views

app_name = "accounts"

urlpatterns = [
    path("intra/", views.AppLoginView.as_view(), name="login"),
    path("iesi/", views.AppLogoutView.as_view(), name="logout"),
    path("inregistrare/", views.RegisterView.as_view(), name="register"),
    path("setari/", views.PreferencesView.as_view(), name="preferences"),
    path("parola/", views.AppPasswordChangeView.as_view(), name="password_change"),
]
