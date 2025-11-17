from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User, UserDevice


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


@admin.register(UserDevice)
class UserDeviceAdmin(admin.ModelAdmin):
    list_display = ['user', 'device_name', 'is_primary', 'last_active', 'created_at']
    list_filter = ['is_primary', 'created_at']
    search_fields = ['user__name', 'device_name', 'device_fingerprint']
    ordering = ['-last_active']
    readonly_fields = ['id', 'last_active', 'created_at']
    
    fieldsets = (
        ('기기 정보', {
            'fields': ('user', 'device_name', 'device_fingerprint', 'is_primary')
        }),
        ('암호화 키', {
            'fields': ('encrypted_private_key',),
            'classes': ('collapse',)
        }),
        ('날짜', {
            'fields': ('last_active', 'created_at')
        }),
    )

