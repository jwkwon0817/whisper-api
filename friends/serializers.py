from rest_framework import serializers

from accounts.models import User

from .models import Friend


class FriendSerializer(serializers.ModelSerializer):
    """친구 관계 시리얼라이저"""
    requester = serializers.SerializerMethodField()
    receiver = serializers.SerializerMethodField()
    
    class Meta:
        model = Friend
        fields = ['id', 'requester', 'receiver', 'status', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_requester(self, obj: Friend) -> dict:
        """요청자 정보"""
        return {
            'id': str(obj.requester.id),
            'name': obj.requester.name,
            'profile_image': obj.requester.profile_image,
        }
    
    def get_receiver(self, obj: Friend) -> dict:
        """수신자 정보"""
        return {
            'id': str(obj.receiver.id),
            'name': obj.receiver.name,
            'profile_image': obj.receiver.profile_image,
        }


class FriendRequestSerializer(serializers.Serializer):
    """친구 요청 시리얼라이저"""
    phone_number = serializers.CharField(
        required=True,
        help_text="친구로 추가할 사용자의 전화번호 (예: 01012345678)"
    )
    
    def validate_phone_number(self, value):
        """전화번호 형식 검증"""
        import re
        pattern = r'^01[0-9]{9}$'
        if not re.match(pattern, value):
            raise serializers.ValidationError("올바른 전화번호 형식이 아닙니다. (예: 01012345678)")
        return value


class FriendResponseSerializer(serializers.Serializer):
    """친구 요청 응답 시리얼라이저"""
    action = serializers.ChoiceField(
        choices=['accept', 'reject'],
        required=True,
        help_text="수락(accept) 또는 거절(reject)"
    )

