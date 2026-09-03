from django.contrib import admin

from apps.search.models import RecentSearch


@admin.register(RecentSearch)
class RecentSearchAdmin(admin.ModelAdmin):
    list_display = ("query", "owner", "hit_count", "last_used_at")
    search_fields = ("query",)
