from django.contrib import admin

from apps.core.admin import SoftDeleteAdmin
from apps.notes.models import ChecklistItem, Note, NoteCategory


class ChecklistItemInline(admin.TabularInline):
    model = ChecklistItem
    extra = 0


@admin.register(Note)
class NoteAdmin(SoftDeleteAdmin):
    list_display = ("title", "owner", "category", "is_pinned", "source", "updated_at")
    list_filter = ("source", "is_pinned", "category")
    search_fields = ("title", "content")
    inlines = (ChecklistItemInline,)
    date_hierarchy = "created_at"


@admin.register(NoteCategory)
class NoteCategoryAdmin(SoftDeleteAdmin):
    list_display = ("name", "owner", "color", "position")
    search_fields = ("name",)
