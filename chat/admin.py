from django.contrib import admin

from .models import (ChatFolder, ChatFolderRoom, ChatRoom, ChatRoomMember,
                     Message)


@admin.register(ChatRoom)
class ChatRoomAdmin(admin.ModelAdmin):
    list_display = ['id', 'room_type', 'name', 'created_by', 'member_count', 'created_at']
    list_filter = ['room_type', 'created_at']
    search_fields = ['name', 'id']
    readonly_fields = ['id', 'created_at', 'updated_at']
    ordering = ['-updated_at']


@admin.register(ChatRoomMember)
class ChatRoomMemberAdmin(admin.ModelAdmin):
    list_display = ['id', 'room', 'user', 'role', 'joined_at']
    list_filter = ['role', 'joined_at']
    search_fields = ['room__name', 'user__name', 'user__phone_number']
    readonly_fields = ['id', 'joined_at']
    ordering = ['-joined_at']


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ['id', 'room', 'sender', 'message_type', 'content_preview', 'created_at']
    list_filter = ['message_type', 'is_read', 'created_at']
    search_fields = ['content', 'sender__name', 'room__name']
    readonly_fields = ['id', 'created_at', 'updated_at']
    ordering = ['-created_at']
    
    def content_preview(self, obj):
        return obj.content[:50] + '...' if len(obj.content) > 50 else obj.content
    content_preview.short_description = '내용 미리보기'


@admin.register(ChatFolder)
class ChatFolderAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'name', 'color', 'order', 'created_at']
    list_filter = ['created_at']
    search_fields = ['name', 'user__name']
    readonly_fields = ['id', 'created_at', 'updated_at']
    ordering = ['order', 'created_at']


@admin.register(ChatFolderRoom)
class ChatFolderRoomAdmin(admin.ModelAdmin):
    list_display = ['id', 'folder', 'room', 'order', 'created_at']
    list_filter = ['created_at']
    search_fields = ['folder__name', 'room__name']
    readonly_fields = ['id', 'created_at']
    ordering = ['order', 'created_at']
