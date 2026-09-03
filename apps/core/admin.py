from django.contrib import admin
from django.utils import timezone

from apps.core.models import AuditLog


class TrashStateFilter(admin.SimpleListFilter):
    title = "stare"
    parameter_name = "stare"

    def lookups(self, request, model_admin):
        return (("active", "Active"), ("cos", "În coș"), ("toate", "Toate"))

    def queryset(self, request, queryset):
        value = self.value() or "active"
        if value == "active":
            return queryset.filter(deleted_at__isnull=True)
        if value == "cos":
            return queryset.filter(deleted_at__isnull=False)
        return queryset


class SoftDeleteAdmin(admin.ModelAdmin):
    """Adminul trebuie sa vada si cosul, deci foloseste `all_objects`."""

    readonly_fields = ("deleted_at",)
    actions = ("restore_selected", "hard_delete_selected")

    def get_queryset(self, request):
        return self.model.all_objects.all()

    def get_list_filter(self, request):
        return (TrashStateFilter, *super().get_list_filter(request))

    @admin.action(description="Restaurează din coș")
    def restore_selected(self, request, queryset):
        count = queryset.update(deleted_at=None, deleted_by_cascade=False)
        self.message_user(request, f"{count} obiecte restaurate.")

    @admin.action(description="Șterge definitiv (ireversibil)")
    def hard_delete_selected(self, request, queryset):
        count = queryset.count()
        queryset.hard_delete()
        self.message_user(request, f"{count} obiecte șterse definitiv.")

    @admin.display(boolean=True, description="în coș")
    def in_trash(self, obj):
        return obj.deleted_at is not None


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "user", "object_label", "object_id")
    list_filter = ("action", "created_at")
    search_fields = ("object_label", "object_id")
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False


admin.site.site_header = "Voice Task — administrare"
admin.site.site_title = "Voice Task"
admin.site.index_title = f"Administrare · {timezone.localdate():%d.%m.%Y}"
