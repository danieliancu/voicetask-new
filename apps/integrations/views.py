from datetime import timedelta

import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import DetailView, ListView, TemplateView

from apps.core.mixins import OwnerQuerysetMixin
from apps.core.models import AuditLog
from apps.core.providers.registry import get_provider
from apps.integrations import oauth, sync
from apps.integrations.models import ConnectedAccount, EmailReference


class IntegrationStatusView(OwnerQuerysetMixin, TemplateView):
    template_name = "integrations/status.html"

    def get_queryset(self):
        return None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        accounts = {
            account.provider: account
            for account in ConnectedAccount.objects.for_user(self.request.user)
        }
        gmail_provider = get_provider("gmail")
        context.update(
            {
                "page": "integrations",
                "gmail": accounts.get(ConnectedAccount.Provider.GMAIL),
                "calendar": accounts.get(ConnectedAccount.Provider.CALENDAR),
                "oauth_configured": oauth.is_configured(),
                "gmail_scope_level": settings.GMAIL_SCOPE_LEVEL,
                "gmail_supports_snippets": gmail_provider.supports_snippets(),
                "gmail_is_mock": gmail_provider.is_mock,
                "calendar_is_mock": get_provider("calendar").is_mock,
            }
        )
        return context


@login_required
def connect(request, provider: str):
    """Fara credentiale Google, oferim varianta demonstrativa in loc sa esuam."""
    if provider not in ConnectedAccount.Provider.values:
        raise Http404
    if not oauth.is_configured():
        messages.info(
            request,
            "Nu există credențiale Google configurate pe acest server. Poți activa "
            "modul demonstrativ, cu date de exemplu.",
        )
        return redirect("integrations:status")
    return HttpResponseRedirect(oauth.authorization_url(request.user.pk, provider))


@login_required
@require_POST
def enable_demo(request, provider: str):
    """Activeaza providerul demonstrativ, marcat explicit ca atare in interfata."""
    if provider not in ConnectedAccount.Provider.values:
        raise Http404
    account, _ = ConnectedAccount.objects.update_or_create(
        owner=request.user,
        provider=provider,
        defaults={
            "status": ConnectedAccount.Status.MOCK,
            "email": f"demo@{provider}.local",
            "scopes": oauth.scopes_for(provider),
            "external_account_id": f"demo-{provider}",
        },
    )
    AuditLog.objects.create(
        user=request.user,
        action=AuditLog.Action.CONNECT,
        object_label=ConnectedAccount._meta.label,
        object_id=str(account.pk),
        detail={"mod": "demonstrativ", "serviciu": provider},
    )
    result = (
        sync.sync_emails(request.user, account)
        if provider == ConnectedAccount.Provider.GMAIL
        else sync.sync_calendar(request.user, account)
    )
    if result.ok:
        messages.success(
            request, f"Mod demonstrativ activat. Am importat {result.created} element(e)."
        )
    else:
        messages.error(request, result.error)
    return redirect("integrations:status")


@login_required
def callback(request):
    """Primeste codul de la Google si salveaza tokenurile criptat."""
    state = request.GET.get("state", "")
    parsed = oauth.unsign_state(state)
    if parsed is None or parsed[0] != request.user.pk:
        messages.error(request, "Cererea de autorizare nu a putut fi verificată.")
        return redirect("integrations:status")
    _, provider = parsed

    error = request.GET.get("error")
    if error:
        messages.error(request, "Autorizarea a fost refuzată.")
        return redirect("integrations:status")

    code = request.GET.get("code", "")
    if not code:
        messages.error(request, "Nu am primit codul de autorizare.")
        return redirect("integrations:status")

    try:
        tokens = oauth.exchange_code(code)
    except (requests.RequestException, ValueError):
        messages.error(request, "Schimbul de token a eșuat. Încearcă din nou.")
        return redirect("integrations:status")

    account, _ = ConnectedAccount.objects.get_or_create(owner=request.user, provider=provider)
    account.access_token = tokens.get("access_token", "")
    if tokens.get("refresh_token"):
        account.refresh_token = tokens["refresh_token"]
    account.token_expires_at = timezone.now() + timedelta(
        seconds=int(tokens.get("expires_in", 3600))
    )
    account.scopes = oauth.scopes_for(provider)
    account.status = ConnectedAccount.Status.CONNECTED
    account.last_error = ""
    account.save()

    AuditLog.objects.create(
        user=request.user,
        action=AuditLog.Action.CONNECT,
        object_label=ConnectedAccount._meta.label,
        object_id=str(account.pk),
        detail={"serviciu": provider},
    )
    messages.success(request, "Contul a fost conectat.")
    return redirect("integrations:status")


@login_required
@require_POST
def disconnect(request, pk: int):
    account = get_object_or_404(ConnectedAccount.objects.for_user(request.user), pk=pk)
    account.access_token = ""
    account.refresh_token = ""
    account.status = ConnectedAccount.Status.DISCONNECTED
    account.token_expires_at = None
    account.save()
    AuditLog.objects.create(
        user=request.user,
        action=AuditLog.Action.DISCONNECT,
        object_label=ConnectedAccount._meta.label,
        object_id=str(account.pk),
    )
    messages.success(request, "Contul a fost deconectat.")
    return redirect("integrations:status")


@login_required
@require_POST
def sync_now(request, pk: int):
    account = get_object_or_404(ConnectedAccount.objects.for_user(request.user), pk=pk)
    if account.provider == ConnectedAccount.Provider.GMAIL:
        result = sync.sync_emails(request.user, account)
    else:
        result = sync.sync_calendar(request.user, account)
    return render(
        request,
        "integrations/_account_card.html",
        {"account": account, "result": result},
    )


class EmailListView(OwnerQuerysetMixin, ListView):
    model = EmailReference
    template_name = "integrations/email_list.html"
    context_object_name = "emails"
    paginate_by = 25

    def get_queryset(self):
        queryset = super().get_queryset()
        status = self.request.GET.get("stare", "")
        if status in EmailReference.Status.values:
            queryset = queryset.filter(status=status)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page": "integrations",
                "statuses": EmailReference.Status.choices,
                "selected_status": self.request.GET.get("stare", ""),
            }
        )
        return context


class EmailDetailView(OwnerQuerysetMixin, DetailView):
    model = EmailReference
    template_name = "integrations/email_detail.html"
    context_object_name = "email"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page"] = "integrations"
        return context


@login_required
@require_POST
def toggle_follow_up(request, pk: int):
    email = get_object_or_404(EmailReference.objects.for_user(request.user), pk=pk)
    if email.status == EmailReference.Status.FOLLOW_UP:
        email.status = EmailReference.Status.DONE
        email.follow_up_at = None
    else:
        email.status = EmailReference.Status.FOLLOW_UP
        email.follow_up_at = email.follow_up_at or timezone.now() + timedelta(days=1)
    email.save(update_fields=["status", "follow_up_at", "updated_at"])
    return render(request, "integrations/_email_row.html", {"email": email})
