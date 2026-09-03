from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from apps.accounts.models import UserPreference

User = get_user_model()


class RomanianAuthenticationForm(AuthenticationForm):
    error_messages = {
        "invalid_login": "Numele de utilizator sau parola nu sunt corecte.",
        "inactive": "Acest cont este dezactivat.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Nume utilizator"
        self.fields["username"].widget.attrs.update({"autocomplete": "username", "autofocus": True})
        self.fields["password"].label = "Parolă"
        self.fields["password"].widget.attrs.update({"autocomplete": "current-password"})


class RegistrationForm(UserCreationForm):
    email = forms.EmailField(label="Email", required=False)

    class Meta:
        model = User
        fields = ("username", "email")
        labels = {"username": "Nume utilizator"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password1"].label = "Parolă"
        self.fields["password2"].label = "Confirmă parola"
        self.fields["username"].help_text = "Litere, cifre și @/./+/-/_"


class PreferenceForm(forms.ModelForm):
    class Meta:
        model = UserPreference
        fields = (
            "display_name",
            "timezone",
            "brief_time",
            "brief_audio_enabled",
            "brief_polish_enabled",
            "notifications_enabled",
            "default_reminder_offset",
        )
        widgets = {
            "brief_time": forms.TimeInput(attrs={"type": "time"}),
            "default_reminder_offset": forms.NumberInput(attrs={"min": 0, "max": 10080, "step": 5}),
        }
        help_texts = {
            "brief_polish_enabled": (
                "Textul rămâne generat din datele tale; AI-ul doar reformulează. "
                "Necesită o cheie OpenAI configurată."
            ),
            "default_reminder_offset": "Cu câte minute înainte să sune alarma implicită.",
        }
