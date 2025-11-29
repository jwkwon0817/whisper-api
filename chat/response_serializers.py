"""
Chat API Swagger 응답 전용 시리얼라이저
"""

from rest_framework import serializers

from .serializers import MessageSerializer


class MessageListResponseSerializer(serializers.Serializer):
    """메시지 목록 응답"""
    results = MessageSerializer(many=True, read_only=True)
    page = serializers.IntegerField(read_only=True)
    page_size = serializers.IntegerField(read_only=True)
    total = serializers.IntegerField(read_only=True)
    has_next = serializers.BooleanField(read_only=True)


class MessageReadResponseSerializer(serializers.Serializer):
    """메시지 읽음 처리 응답"""
    message = serializers.CharField(read_only=True)
    read_count = serializers.IntegerField(read_only=True)


class ChatRoomLeaveResponseSerializer(serializers.Serializer):
    """채팅방 나가기 응답"""
    message = serializers.CharField(read_only=True)

