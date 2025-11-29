from rest_framework import serializers

from accounts.models import User

from .models import Friend


class FriendUserSerializer(serializers.Serializer):
    """친구 목록에 표시되는 사용자 정보 시리얼라이저"""
    id = serializers.UUIDField(read_only=True, help_text="사용자 ID")
    name = serializers.CharField(read_only=True, help_text="사용자 이름")
    profile_image = serializers.URLField(read_only=True, allow_null=True, help_text="프로필 이미지 URL")


class FriendSerializer(serializers.ModelSerializer):
    """친구 관계 시리얼라이저"""
    requester = FriendUserSerializer(read_only=True, help_text="요청자 정보")
    receiver = FriendUserSerializer(read_only=True, help_text="수신자 정보")
    
    class Meta:
        model = Friend
        fields = ['id', 'requester', 'receiver', 'status', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def to_representation(self, instance):
        """직렬화 시 사용자 정보를 올바른 형식으로 변환"""
        representation = super().to_representation(instance)
        representation['requester'] = {
            'id': str(instance.requester.id),
            'name': instance.requester.name,
            'profile_image': instance.requester.profile_image,
        }
        representation['receiver'] = {
            'id': str(instance.receiver.id),
            'name': instance.receiver.name,
            'profile_image': instance.receiver.profile_image,
        }
        return representation


class FriendListItemSerializer(serializers.Serializer):
    """친구 목록 아이템 시리얼라이저 (상대방 정보만 반환)"""
    id = serializers.UUIDField(read_only=True, help_text="친구 관계 ID (삭제 시 사용)")
    user = FriendUserSerializer(read_only=True, help_text="친구 사용자 정보")


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

