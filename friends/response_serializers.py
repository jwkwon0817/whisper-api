from rest_framework import serializers


class MessageResponseSerializer(serializers.Serializer):
    message = serializers.CharField(read_only=True)


class FriendRequestCountResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField(read_only=True)

