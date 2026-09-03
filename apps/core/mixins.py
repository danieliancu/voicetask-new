"""Mixin-uri pentru view-uri: izolare pe utilizator si raspunsuri partiale HTMX."""

from __future__ import annotations

from django.contrib.auth.mixins import LoginRequiredMixin


class OwnerQuerysetMixin(LoginRequiredMixin):
    """Restrange orice queryset la obiectele utilizatorului curent.

    Un PK strain produce 404, nu 403: nu confirmam existenta obiectului altcuiva.
    """

    owner_field = "owner"
    include_deleted = False

    def get_base_manager(self):
        model = getattr(self, "model", None) or self.queryset.model
        if self.include_deleted and hasattr(model, "all_objects"):
            return model.all_objects
        return model._default_manager

    def get_queryset(self):
        return self.get_base_manager().all().filter(**{self.owner_field: self.request.user})


class OwnerFormMixin:
    """Seteaza proprietarul la salvare si transmite userul formularului."""

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        form.instance.owner = self.request.user
        return super().form_valid(form)


class HtmxPartialMixin:
    """Randeaza `partial_template_name` cand cererea vine de la HTMX."""

    partial_template_name: str | None = None

    def get_template_names(self):
        if self.partial_template_name and getattr(self.request, "htmx", False):
            return [self.partial_template_name]
        return super().get_template_names()


class UserFormKwargMixin:
    """Formular care primeste `user` si isi ingusteaza singur cheile straine."""

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.limit_querysets()

    def limit_querysets(self) -> None:
        """Suprascris de formularele cu campuri ForeignKey."""
