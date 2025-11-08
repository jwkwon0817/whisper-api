from rest_framework import serializers
from accounts.models import Asset
from accounts.models import User
from .models import ChatFolder, ChatFolderRoom, ChatRoom, ChatRoomMember, Message


class UserBasicSerializer(serializers.ModelSerializer):
    """사용자 기본 정보 시리얼라이저"""
    
    class Meta:
        model = User
        fields = ['id', 'name', 'profile_image']
        read_only_fields = ['id']


class ChatRoomMemberSerializer(serializers.ModelSerializer):
    """채팅방 멤버 시리얼라이저"""
    user = UserBasicSerializer(read_only=True)
    
    class Meta:
        model = ChatRoomMember
        fields = ['id', 'user', 'role', 'nickname', 'joined_at', 'last_read_at']
        read_only_fields = ['id', 'joined_at']


class MessageSerializer(serializers.ModelSerializer):
    """메시지 시리얼라이저"""
    sender = UserBasicSerializer(read_only=True)
    reply_to = serializers.SerializerMethodField()
    
    class Meta:
        model = Message
        fields = [
            'id', 'room', 'sender', 'message_type', 'content',
            'asset', 'reply_to', 'is_read', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_reply_to(self, obj):
        """답장 대상 메시지 정보"""
        if obj.reply_to:
            return {
                'id': str(obj.reply_to.id),
                'sender': UserBasicSerializer(obj.reply_to.sender).data,
                'content': obj.reply_to.content[:50],
                'message_type': obj.reply_to.message_type,
            }
        return None


class ChatRoomSerializer(serializers.ModelSerializer):
    """채팅방 시리얼라이저"""
    members = ChatRoomMemberSerializer(many=True, read_only=True)
    member_count = serializers.IntegerField(read_only=True)
    last_message = serializers.SerializerMethodField()
    created_by = UserBasicSerializer(read_only=True)
    
    class Meta:
        model = ChatRoom
        fields = [
            'id', 'room_type', 'name', 'description', 'created_by',
            'members', 'member_count', 'last_message', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_last_message(self, obj):
        """마지막 메시지 정보"""
        last_msg = obj.last_message
        if last_msg:
            return MessageSerializer(last_msg).data
        return None


class ChatRoomCreateSerializer(serializers.Serializer):
    """채팅방 생성 시리얼라이저"""
    room_type = serializers.ChoiceField(choices=['direct', 'group'], required=True)
    name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    member_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        help_text="초대할 사용자 ID 리스트 (1:1 채팅의 경우 상대방 ID만 필요)"
    )


class MessageCreateSerializer(serializers.ModelSerializer):
    """메시지 생성 시리얼라이저"""
    reply_to_id = serializers.UUIDField(required=False, allow_null=True, write_only=True)
    
    class Meta:
        model = Message
        fields = ['room', 'message_type', 'content', 'asset', 'reply_to_id']
    
    def create(self, validated_data):
        reply_to_id = validated_data.pop('reply_to_id', None)
        room = validated_data['room']
        sender = self.context['request'].user
        
        # 채팅방 멤버인지 확인
        if not ChatRoomMember.objects.filter(room=room, user=sender).exists():
            raise serializers.ValidationError({'room': '채팅방 멤버가 아닙니다.'})
        
        # 답장 대상 메시지 설정
        reply_to = None
        if reply_to_id:
            try:
                reply_to = Message.objects.get(id=reply_to_id, room=room)
            except Message.DoesNotExist:
                raise serializers.ValidationError({'reply_to_id': '존재하지 않는 메시지입니다.'})
        
        validated_data['sender'] = sender
        validated_data['reply_to'] = reply_to
        
        return super().create(validated_data)


class ChatFolderSerializer(serializers.ModelSerializer):
    """채팅방 폴더 시리얼라이저"""
    room_count = serializers.SerializerMethodField()
    
    class Meta:
        model = ChatFolder
        fields = ['id', 'name', 'color', 'order', 'room_count', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_room_count(self, obj):
        """폴더에 포함된 채팅방 수"""
        return obj.rooms.count()


class ChatFolderRoomSerializer(serializers.ModelSerializer):
    """폴더-채팅방 연결 시리얼라이저"""
    room = ChatRoomSerializer(read_only=True)
    
    class Meta:
        model = ChatFolderRoom
        fields = ['id', 'folder', 'room', 'order', 'created_at']
        read_only_fields = ['id', 'created_at']

