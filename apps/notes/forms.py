from django import forms

from apps.core.mixins import UserFormKwargMixin
from apps.notes.models import Note, NoteCategory


class NoteForm(UserFormKwargMixin, forms.ModelForm):
    class Meta:
        model = Note
        fields = ("title", "content", "category", "is_pinned")
        widgets = {
            "content": forms.Textarea(attrs={"rows": 8}),
            "title": forms.TextInput(attrs={"autocomplete": "off"}),
        }

    def limit_querysets(self) -> None:
        if self.user is not None:
            self.fields["category"].queryset = NoteCategory.objects.for_user(self.user)
        self.fields["category"].empty_label = "Fără categorie"


class NoteCategoryForm(UserFormKwargMixin, forms.ModelForm):
    class Meta:
        model = NoteCategory
        fields = ("name", "color", "icon")
