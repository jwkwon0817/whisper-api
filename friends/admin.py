from django.contrib import admin

from .models import Friend


@admin.register(Friend)
class FriendAdmin(admin.ModelAdmin):
    list_display = ['requester', 'receiver', 'status', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['requester__name', 'receiver__name']
    readonly_fields = ['id', 'created_at', 'updated_at']
    ordering = ['-created_at']
