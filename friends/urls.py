from django.urls import path

from .views import (
    FriendDeleteView,
    FriendListView,
    FriendRequestListView,
    FriendRequestView,
    FriendResponseView,
)

urlpatterns = [
    path('friends/requests/', FriendRequestView.as_view(), name='friend-request'),
    path('friends/', FriendListView.as_view(), name='friend-list'),
    path('friends/requests/received/', FriendRequestListView.as_view(), name='friend-request-list'),
    path('friends/requests/<uuid:friend_id>/', FriendResponseView.as_view(), name='friend-response'),
    path('friends/<uuid:friend_id>/', FriendDeleteView.as_view(), name='friend-delete'),
]

