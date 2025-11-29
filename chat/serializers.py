from typing import Any, Dict, Optional

from rest_framework import serializers

from accounts.models import User
from common.models import Asset
from common.serializers import AssetSerializer

from .models import (
    ChatFolder,
    ChatFolderRoom,
    ChatRoom,
    ChatRoomMember,
    DirectChatInvitation,
    GroupChatInvitation,
    Message,
)


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
    id = serializers.UUIDField(read_only=True, format='hex_verbose')  # UUID를 문자열로 직렬화
    room = serializers.UUIDField(read_only=True, format='hex_verbose')  # UUID를 문자열로 직렬화
    sender = UserBasicSerializer(read_only=True, allow_null=True)
    asset = AssetSerializer(read_only=True)  # Asset 객체로 직렬화
    reply_to = serializers.SerializerMethodField()
    content = serializers.SerializerMethodField()
    encrypted_content = serializers.SerializerMethodField()
    encrypted_session_key = serializers.SerializerMethodField()
    self_encrypted_session_key = serializers.SerializerMethodField()
    
    class Meta:
        model = Message
        fields = [
            'id', 'room', 'sender', 'message_type', 'content',
            'encrypted_content', 'encrypted_session_key', 'self_encrypted_session_key', 'asset', 'reply_to', 'is_read', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_content(self, obj: Message) -> str:
        """그룹 채팅인 경우에만 content 반환"""
        if obj.room.room_type == 'group':
            return obj.content
        # 1:1 채팅인 경우 빈 값 또는 메타데이터만 반환
        return obj.content if obj.content else ''
    
    def get_encrypted_content(self, obj: Message) -> Optional[str]:
        """1:1 채팅인 경우에만 encrypted_content 반환"""
        if obj.room.room_type == 'direct':
            return obj.encrypted_content
        # 그룹 채팅인 경우 null 반환
        return None
    
    def get_encrypted_session_key(self, obj: Message) -> Optional[str]:
        """1:1 채팅인 경우에만 encrypted_session_key 반환"""
        if obj.room.room_type == 'direct':
            return obj.encrypted_session_key
        # 그룹 채팅인 경우 null 반환
        return None
    
    def get_self_encrypted_session_key(self, obj: Message) -> Optional[str]:
        """1:1 채팅인 경우에만 self_encrypted_session_key 반환"""
        if obj.room.room_type == 'direct':
            return obj.self_encrypted_session_key
        # 그룹 채팅인 경우 null 반환
        return None
    
    def get_reply_to(self, obj: Message) -> Optional[Dict[str, Any]]:
        """답장 대상 메시지 정보"""
        if obj.reply_to:
            reply_to = obj.reply_to
            reply_content = ''
            if reply_to.room.room_type == 'group':
                reply_content = reply_to.content[:50]
            elif reply_to.encrypted_content:
                reply_content = '[암호화된 메시지]'
            
            sender_data = None
            if reply_to.sender:
                sender_data = UserBasicSerializer(reply_to.sender).data
            
            return {
                'id': str(reply_to.id),
                'sender': sender_data,
                'content': reply_content,
                'message_type': reply_to.message_type,
                'encrypted_content': reply_to.encrypted_content,
                'encrypted_session_key': reply_to.encrypted_session_key,
                'self_encrypted_session_key': reply_to.self_encrypted_session_key,
            }
        return None


class ChatRoomSerializer(serializers.ModelSerializer):
    """채팅방 시리얼라이저"""
    members = ChatRoomMemberSerializer(many=True, read_only=True)
    member_count = serializers.IntegerField(read_only=True)
    last_message = serializers.SerializerMethodField()
    created_by = UserBasicSerializer(read_only=True)
    name = serializers.SerializerMethodField()
    folder_ids = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()
    
    class Meta:
        model = ChatRoom
        fields = [
            'id', 'room_type', 'name', 'description', 'created_by',
            'members', 'member_count', 'last_message', 'folder_ids', 'unread_count', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_name(self, obj: ChatRoom) -> Optional[str]:
        """1:1 채팅인 경우 상대방 이름 반환, 그룹 채팅인 경우 채팅방 이름 반환"""
        if obj.room_type == 'direct':
            # 현재 요청한 사용자 찾기
            request = self.context.get('request')
            if request and request.user:
                # 상대방 찾기
                other_member = obj.members.exclude(user=request.user).first()
                if other_member:
                    return other_member.user.name
        # 그룹 채팅이거나 상대방을 찾을 수 없는 경우 원래 이름 반환
        return obj.name
    
    def get_last_message(self, obj: ChatRoom) -> Optional[Dict[str, Any]]:
        """마지막 메시지 정보"""
        # prefetch된 last_message_list에서 첫 번째 메시지 가져오기
        if hasattr(obj, 'last_message_list') and obj.last_message_list:
            last_msg = obj.last_message_list[0]
            return MessageSerializer(last_msg, context=self.context).data
        # fallback: 모델의 last_message 프로퍼티 사용
        last_msg = obj.last_message
        if last_msg:
            return MessageSerializer(last_msg, context=self.context).data
        return None
    
    def get_folder_ids(self, obj: ChatRoom) -> list[str]:
        """채팅방이 속한 폴더 ID 목록"""
        # prefetch된 user_folder_rooms 사용
        if hasattr(obj, 'user_folder_rooms'):
            return [str(fr.folder.id) for fr in obj.user_folder_rooms]
        # fallback: 직접 조회
        request = self.context.get('request')
        if request and request.user:
            folder_rooms = obj.folders.filter(folder__user=request.user)
            return [str(fr.folder.id) for fr in folder_rooms]
        return []
    
    def get_unread_count(self, obj: ChatRoom) -> int:
        """읽지 않은 메시지 수"""
        request = self.context.get('request')
        if not request or not request.user:
            return 0
        
        # 현재 사용자의 마지막 읽은 시간 가져오기
        try:
            member = obj.members.filter(user=request.user).first()
            if not member or not member.last_read_at:
                # 읽은 기록이 없으면 모든 메시지가 읽지 않은 것으로 간주
                return Message.objects.filter(room=obj).exclude(sender=request.user).count()
            
            # 마지막 읽은 시간 이후의 메시지 수
            return Message.objects.filter(
                room=obj,
                created_at__gt=member.last_read_at
            ).exclude(sender=request.user).count()
        except Exception:
            return 0


class DirectChatCreateSerializer(serializers.Serializer):
    """1:1 채팅 생성 시리얼라이저"""
    user_id = serializers.UUIDField(
        required=True,
        help_text="1:1 채팅을 시작할 상대방 사용자 ID"
    )


class GroupChatCreateSerializer(serializers.Serializer):
    """그룹 채팅 생성 시리얼라이저"""
    name = serializers.CharField(max_length=100, required=True, help_text="그룹 채팅방 이름")
    description = serializers.CharField(required=False, allow_blank=True)
    member_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        help_text="초대할 사용자 ID 리스트"
    )


class MessageCreateSerializer(serializers.ModelSerializer):
    """메시지 생성 시리얼라이저"""
    reply_to_id = serializers.UUIDField(required=False, allow_null=True, write_only=True)
    encrypted_content = serializers.CharField(
        required=False, 
        allow_blank=True, 
        allow_null=True,
        help_text='암호화된 메시지 내용 (AES 암호화, 1:1 채팅인 경우 필수, 그룹 채팅인 경우 사용하지 않음)'
    )
    encrypted_session_key = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text='암호화된 세션 키 (RSA 암호화, 상대방 공개키로 암호화, 하이브리드 암호화 방식인 경우 필수, 기존 방식인 경우 선택)'
    )
    self_encrypted_session_key = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text='자기 암호화된 세션 키 (RSA 암호화, 내 공개키로 암호화, 양방향 암호화 지원용, 선택사항)'
    )
    
    class Meta:
        model = Message
        fields = ['message_type', 'content', 'encrypted_content', 'encrypted_session_key', 'self_encrypted_session_key', 'asset', 'reply_to_id']
    
    def validate(self, attrs):
        """채팅방 타입에 따른 검증"""
        # room은 path parameter에서 가져오므로 context에서 가져옴
        room = self.context.get('room')
        
        if not room:
            # room이 context에 없으면 create 메서드에서 처리
            return attrs
        
        encrypted_content = attrs.get('encrypted_content')
        encrypted_session_key = attrs.get('encrypted_session_key')
        self_encrypted_session_key = attrs.get('self_encrypted_session_key')
        content = attrs.get('content')
        
        # 1:1 채팅인 경우
        if room.room_type == 'direct':
            if not encrypted_content:
                raise serializers.ValidationError({
                    'encrypted_content': '1:1 채팅에서는 암호화된 메시지(encrypted_content)가 필수입니다.'
                })

            if not content:
                attrs['content'] = ''  # 빈 값으로 설정
        
        # 그룹 채팅인 경우
        else:
            if encrypted_content:
                raise serializers.ValidationError({
                    'encrypted_content': '그룹 채팅에서는 암호화된 메시지를 사용할 수 없습니다.'
                })
            if encrypted_session_key:
                raise serializers.ValidationError({
                    'encrypted_session_key': '그룹 채팅에서는 암호화된 세션 키를 사용할 수 없습니다.'
                })
            if self_encrypted_session_key:
                raise serializers.ValidationError({
                    'self_encrypted_session_key': '그룹 채팅에서는 자기 암호화된 세션 키를 사용할 수 없습니다.'
                })
            if not content:
                raise serializers.ValidationError({
                    'content': '그룹 채팅에서는 메시지 내용(content)이 필수입니다.'
                })
        
        return attrs
    
    def create(self, validated_data):
        reply_to_id = validated_data.pop('reply_to_id', None)
        # room은 path parameter에서 가져옴 (view에서 context로 전달)
        room = self.context.get('room')
        if not room:
            raise serializers.ValidationError({'room': '채팅방 정보가 없습니다.'})
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
        
        validated_data['room'] = room
        validated_data['sender'] = sender
        validated_data['reply_to'] = reply_to
        
        return super().create(validated_data)


class MessageUpdateSerializer(serializers.ModelSerializer):
    """메시지 수정 시리얼라이저"""
    encrypted_content = serializers.CharField(
        required=False, 
        allow_blank=True, 
        allow_null=True,
        help_text='암호화된 메시지 내용 (수정 시)'
    )
    encrypted_session_key = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text='암호화된 세션 키 (상대방용)'
    )
    self_encrypted_session_key = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text='자기 암호화된 세션 키 (내 복호화용)'
    )
    content = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text='메시지 내용 (그룹챗 수정 시)'
    )
    
    class Meta:
        model = Message
        fields = ['content', 'encrypted_content', 'encrypted_session_key', 'self_encrypted_session_key']
    
    def validate(self, attrs):
        """수정 유효성 검사"""
        if not attrs.get('content') and not attrs.get('encrypted_content'):
             raise serializers.ValidationError("수정할 내용이 없습니다.")
        return attrs


class ChatFolderSerializer(serializers.ModelSerializer):
    """채팅방 폴더 시리얼라이저"""
    room_count = serializers.SerializerMethodField()
    
    class Meta:
        model = ChatFolder
        fields = ['id', 'name', 'color', 'icon', 'order', 'room_count', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_room_count(self, obj: ChatFolder) -> int:
        """폴더에 포함된 채팅방 수"""
        return obj.rooms.count()


class ChatFolderRoomSerializer(serializers.ModelSerializer):
    """폴더-채팅방 연결 시리얼라이저"""
    room = ChatRoomSerializer(read_only=True)
    
    class Meta:
        model = ChatFolderRoom
        fields = ['id', 'folder', 'room', 'order', 'created_at']
        read_only_fields = ['id', 'created_at']
    
    def to_representation(self, instance):
        """representation 생성 시 context 전달"""
        ret = super().to_representation(instance)
        # ChatRoomSerializer에 context 전달
        if 'room' in ret and isinstance(ret['room'], dict):
            room_serializer = ChatRoomSerializer(
                instance.room,
                context=self.context
            )
            ret['room'] = room_serializer.data
        return ret


# 추가 시리얼라이저들
class EmptySerializer(serializers.Serializer):
    """빈 요청 본문용 시리얼라이저"""
    pass


class MessageReadSerializer(serializers.Serializer):
    """메시지 읽음 처리 시리얼라이저"""
    message_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=True,
        help_text="읽음 처리할 메시지 ID 리스트"
    )


class ChatFolderCreateSerializer(serializers.Serializer):
    """채팅방 폴더 생성 시리얼라이저"""
    name = serializers.CharField(required=True, max_length=100)
    color = serializers.CharField(required=False, max_length=7, default='#000000')
    icon = serializers.CharField(required=False, max_length=50, default='folder.fill')


class ChatRoomUpdateSerializer(serializers.Serializer):
    """채팅방 정보 수정 시리얼라이저"""
    name = serializers.CharField(required=False, max_length=100)
    description = serializers.CharField(required=False, allow_blank=True)


class ChatFolderRoomAddSerializer(serializers.Serializer):
    """폴더에 채팅방 추가 시리얼라이저"""
    room_id = serializers.UUIDField(required=True)


class GroupChatInvitationSerializer(serializers.ModelSerializer):
    """그룹챗 초대 시리얼라이저"""
    inviter = UserBasicSerializer(read_only=True)
    invitee = UserBasicSerializer(read_only=True)
    room = ChatRoomSerializer(read_only=True)
    
    class Meta:
        model = GroupChatInvitation
        fields = ['id', 'room', 'inviter', 'invitee', 'status', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class GroupChatInvitationCreateSerializer(serializers.Serializer):
    """그룹챗 초대 생성 시리얼라이저"""
    user_id = serializers.UUIDField(
        required=True,
        help_text="초대할 친구의 사용자 ID"
    )


class GroupChatInvitationResponseSerializer(serializers.Serializer):
    """그룹챗 초대 응답 시리얼라이저"""
    action = serializers.ChoiceField(
        choices=['accept', 'reject'],
        required=True,
        help_text="수락(accept) 또는 거절(reject)"
    )


class DirectChatInvitationSerializer(serializers.ModelSerializer):
    """1:1 채팅 초대 시리얼라이저"""
    inviter = UserBasicSerializer(read_only=True)
    invitee = UserBasicSerializer(read_only=True)
    room_type = serializers.SerializerMethodField()
    members = serializers.SerializerMethodField()
    
    class Meta:
        model = DirectChatInvitation
        fields = ['id', 'room_type', 'inviter', 'invitee', 'members', 'status', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_room_type(self, obj):
        """1:1 채팅 초대는 항상 'direct' 타입"""
        return 'direct'
    
    def get_members(self, obj):
        """초대자와 초대받은 사람을 멤버로 반환"""
        return [
            UserBasicSerializer(obj.inviter).data,
            UserBasicSerializer(obj.invitee).data,
        ]


class DirectChatInvitationResponseSerializer(serializers.Serializer):
    """1:1 채팅 초대 응답 시리얼라이저"""
    action = serializers.ChoiceField(
        choices=['accept', 'reject'],
        required=True,
        help_text="수락(accept) 또는 거절(reject)"
    )


class ChatInvitationListSerializer(serializers.Serializer):
    """통합 채팅 초대 목록 시리얼라이저 (1:1 + 그룹)"""
    id = serializers.UUIDField()
    type = serializers.ChoiceField(choices=['direct', 'group'])
    inviter = UserBasicSerializer()
    invitee = UserBasicSerializer()
    room = ChatRoomSerializer(required=False, allow_null=True)  # 1:1은 room 없음
    status = serializers.CharField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
