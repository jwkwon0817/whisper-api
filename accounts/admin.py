from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Asset, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ['phone_number', 'name', 'is_active', 'is_staff', 'created_at']
    list_filter = ['is_active', 'is_staff', 'is_superuser', 'created_at']
    search_fields = ['phone_number', 'name']
    ordering = ['-created_at']
    
    fieldsets = (
        (None, {'fields': ('phone_number', 'password')}),
        ('개인 정보', {'fields': ('name', 'profile_image', 'public_key')}),
        ('권한', {'fields': ('is_active', 'is_staff', 'is_superuser')}),
        ('날짜', {'fields': ('last_login', 'created_at', 'updated_at')}),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('phone_number', 'name', 'password1', 'password2'),
        }),
    )
    
    readonly_fields = ['created_at', 'updated_at', 'last_login']
    
    filter_horizontal = []


@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = ['original_name', 's3_key', 'content_type', 'file_size', 'created_at']
    list_filter = ['content_type', 'created_at']
    search_fields = ['original_name', 's3_key']
    readonly_fields = ['id', 'created_at', 'updated_at']
    ordering = ['-created_at']

