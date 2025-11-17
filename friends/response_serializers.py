"""
Friends API Swagger 응답 전용 시리얼라이저
"""

from rest_framework import serializers


class MessageResponseSerializer(serializers.Serializer):
    """단순 메시지 응답"""
    message = serializers.CharField(read_only=True)


class FriendRequestCountResponseSerializer(serializers.Serializer):
    """친구 요청 수 응답"""
    count = serializers.IntegerField(read_only=True)

