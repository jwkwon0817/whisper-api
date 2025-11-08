from django.urls import path
from .views import (
    ChatFolderDetailView, ChatFolderListView, ChatFolderRoomView,
    ChatRoomDetailView, ChatRoomLeaveView, ChatRoomListView, ChatRoomMemberView, 
    DirectChatCreateView, GroupChatCreateView, GroupChatInvitationListView,
    GroupChatInvitationResponseView, GroupChatInvitationView, MessageListView,
    MessageReadView,
)

urlpatterns = [
    # Chat Room endpoints
    path('chat/rooms/', ChatRoomListView.as_view(), name='chat-room-list'),
    path('chat/rooms/direct/', DirectChatCreateView.as_view(), name='direct-chat-create'),
    path('chat/rooms/group/', GroupChatCreateView.as_view(), name='group-chat-create'),
    path('chat/rooms/<uuid:room_id>/', ChatRoomDetailView.as_view(), name='chat-room-detail'),
    path('chat/rooms/<uuid:room_id>/leave/', ChatRoomLeaveView.as_view(), name='chat-room-leave'),
    path('chat/rooms/<uuid:room_id>/messages/', MessageListView.as_view(), name='message-list'),
    path('chat/rooms/<uuid:room_id>/messages/read/', MessageReadView.as_view(), name='message-read'),
    path('chat/rooms/<uuid:room_id>/members/', ChatRoomMemberView.as_view(), name='chat-room-member-add'),
    path('chat/rooms/<uuid:room_id>/members/<uuid:user_id>/', ChatRoomMemberView.as_view(), name='chat-room-member-remove'),
    path('chat/rooms/<uuid:room_id>/invitations/', GroupChatInvitationView.as_view(), name='group-chat-invitation'),
    path('chat/invitations/', GroupChatInvitationListView.as_view(), name='group-chat-invitation-list'),
    path('chat/invitations/<uuid:invitation_id>/', GroupChatInvitationResponseView.as_view(), name='group-chat-invitation-response'),
    
    # Chat Folder endpoints
    path('chat/folders/', ChatFolderListView.as_view(), name='chat-folder-list'),
    path('chat/folders/<uuid:folder_id>/', ChatFolderDetailView.as_view(), name='chat-folder-detail'),
    path('chat/folders/<uuid:folder_id>/rooms/', ChatFolderRoomView.as_view(), name='chat-folder-room-add'),
    path('chat/folders/<uuid:folder_id>/rooms/<uuid:room_id>/', ChatFolderRoomView.as_view(), name='chat-folder-room-remove'),
]

