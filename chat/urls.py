from django.urls import path
from .views import (
    ChatFolderDetailView, ChatFolderListView, ChatFolderRoomView,
    ChatRoomDetailView, ChatRoomListView, MessageListView,
)

urlpatterns = [
    # Chat Room endpoints
    path('chat/rooms/', ChatRoomListView.as_view(), name='chat-room-list'),
    path('chat/rooms/<uuid:room_id>/', ChatRoomDetailView.as_view(), name='chat-room-detail'),
    path('chat/rooms/<uuid:room_id>/messages/', MessageListView.as_view(), name='message-list'),
    
    # Chat Folder endpoints
    path('chat/folders/', ChatFolderListView.as_view(), name='chat-folder-list'),
    path('chat/folders/<uuid:folder_id>/', ChatFolderDetailView.as_view(), name='chat-folder-detail'),
    path('chat/folders/<uuid:folder_id>/rooms/', ChatFolderRoomView.as_view(), name='chat-folder-room-add'),
    path('chat/folders/<uuid:folder_id>/rooms/<uuid:room_id>/', ChatFolderRoomView.as_view(), name='chat-folder-room-remove'),
]

