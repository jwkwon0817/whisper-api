from django.contrib import admin

from .models import Asset


@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = ['original_name', 's3_key', 'content_type', 'file_size', 'created_at']
    list_filter = ['content_type', 'created_at']
    search_fields = ['original_name', 's3_key']
    readonly_fields = ['id', 'created_at', 'updated_at']
    ordering = ['-created_at']
