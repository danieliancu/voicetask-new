from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, LogoutView, PasswordChangeView
from django.urls import reverse_lazy
from django.views.generic import CreateView, UpdateView

from apps.accounts.forms import PreferenceForm, RegistrationForm, RomanianAuthenticationForm
from apps.accounts.models import UserPreference


class AppLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = RomanianAuthenticationForm
    redirect_authenticated_user = True


class AppLogoutView(LogoutView):
    next_page = reverse_lazy("accounts:login")


class RegisterView(CreateView):
    template_name = "accounts/register.html"
    form_class = RegistrationForm
    success_url = reverse_lazy("core:home")

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            from django.shortcuts import redirect

            return redirect("core:home")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        login(self.request, self.object)
        messages.success(self.request, "Contul a fost creat. Bine ai venit!")
        return response


class PreferencesView(LoginRequiredMixin, UpdateView):
    template_name = "accounts/preferences.html"
    form_class = PreferenceForm
    success_url = reverse_lazy("accounts:preferences")

    def get_object(self, queryset=None):
        return UserPreference.for_user(self.request.user)

    def form_valid(self, form):
        messages.success(self.request, "Preferințele au fost salvate.")
        return super().form_valid(form)


class AppPasswordChangeView(LoginRequiredMixin, PasswordChangeView):
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("accounts:preferences")

    def form_valid(self, form):
        messages.success(self.request, "Parola a fost schimbată.")
        return super().form_valid(form)
