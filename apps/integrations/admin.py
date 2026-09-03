from django.contrib import admin

from apps.core.admin import SoftDeleteAdmin
from apps.integrations.models import ConnectedAccount, EmailReference


@admin.register(ConnectedAccount)
class ConnectedAccountAdmin(admin.ModelAdmin):
    list_display = ("owner", "provider", "status", "email", "last_synced_at")
    list_filter = ("provider", "status")
    # Tokenurile nu se afiseaza si nu se editeaza din admin.
    exclude = ("_access_token", "_refresh_token")
    readonly_fields = ("token_expires_at", "last_synced_at", "last_error")


@admin.register(EmailReference)
class EmailReferenceAdmin(SoftDeleteAdmin):
    list_display = ("subject", "owner", "sender", "status", "received_at", "follow_up_at")
    list_filter = ("status",)
    search_fields = ("subject", "sender")
    date_hierarchy = "received_at"
