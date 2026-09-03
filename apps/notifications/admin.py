from django.contrib import admin

from apps.notifications.models import Notification, NotificationDelivery, PushSubscription


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("title", "owner", "kind", "dedup_key", "read_at", "created_at")
    list_filter = ("kind",)
    search_fields = ("title", "dedup_key")


@admin.register(PushSubscription)
class PushSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("owner", "is_active", "last_used_at", "failure_count")
    list_filter = ("is_active",)


@admin.register(NotificationDelivery)
class NotificationDeliveryAdmin(admin.ModelAdmin):
    list_display = ("notification", "channel", "result", "created_at")
    list_filter = ("channel", "result")
