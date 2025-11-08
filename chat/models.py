import uuid
from django.contrib.auth import get_user_model
from django.db import models

User = get_user_model()


class ChatRoom(models.Model):
    """채팅방 모델"""
    ROOM_TYPE_CHOICES = [
        ('direct', '1:1 채팅'),
        ('group', '그룹 채팅'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room_type = models.CharField(max_length=10, choices=ROOM_TYPE_CHOICES, verbose_name='채팅방 타입')
    name = models.CharField(max_length=100, null=True, blank=True, verbose_name='채팅방 이름')
    description = models.TextField(null=True, blank=True, verbose_name='설명')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_rooms', verbose_name='생성자')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'chat_rooms'
        verbose_name = '채팅방'
        verbose_name_plural = '채팅방'
        ordering = ['-updated_at']
    
    def __str__(self):
        if self.name:
            return f"{self.name} ({self.room_type})"
        return f"{self.room_type} 채팅방 ({self.id})"
    
    @property
    def member_count(self):
        """채팅방 멤버 수"""
        return self.members.count()
    
    @property
    def last_message(self):
        """마지막 메시지"""
        return self.messages.order_by('-created_at').first()


class ChatRoomMember(models.Model):
    """채팅방 멤버 모델"""
    ROLE_CHOICES = [
        ('owner', '방장'),
        ('admin', '관리자'),
        ('member', '멤버'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name='members', verbose_name='채팅방')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_room_memberships', verbose_name='사용자')
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='member', verbose_name='역할')
    nickname = models.CharField(max_length=50, null=True, blank=True, verbose_name='닉네임')
    joined_at = models.DateTimeField(auto_now_add=True)
    last_read_at = models.DateTimeField(null=True, blank=True, verbose_name='마지막 읽은 시간')
    
    class Meta:
        db_table = 'chat_room_members'
        verbose_name = '채팅방 멤버'
        verbose_name_plural = '채팅방 멤버'
        unique_together = [['room', 'user']]
        ordering = ['-joined_at']
    
    def __str__(self):
        return f"{self.user.name} in {self.room}"


class Message(models.Model):
    """메시지 모델"""
    MESSAGE_TYPE_CHOICES = [
        ('text', '텍스트'),
        ('image', '이미지'),
        ('file', '파일'),
        ('system', '시스템 메시지'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name='messages', verbose_name='채팅방')
    sender = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='sent_messages', verbose_name='발신자')
    message_type = models.CharField(max_length=10, choices=MESSAGE_TYPE_CHOICES, default='text', verbose_name='메시지 타입')
    content = models.TextField(verbose_name='메시지 내용 (암호화된 내용)')
    encrypted_content = models.TextField(null=True, blank=True, verbose_name='암호화된 원본 내용')
    asset = models.ForeignKey('common.Asset', on_delete=models.SET_NULL, null=True, blank=True, verbose_name='첨부 파일')
    reply_to = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='replies', verbose_name='답장 대상')
    is_read = models.BooleanField(default=False, verbose_name='읽음 여부')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'messages'
        verbose_name = '메시지'
        verbose_name_plural = '메시지'
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['room', '-created_at']),
            models.Index(fields=['sender', '-created_at']),
        ]
    
    def __str__(self):
        return f"{self.sender.name if self.sender else 'System'}: {self.content[:50]}"


class ChatFolder(models.Model):
    """채팅방 폴더 모델"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_folders', verbose_name='사용자')
    name = models.CharField(max_length=100, verbose_name='폴더 이름')
    color = models.CharField(max_length=7, default='#000000', verbose_name='폴더 색상')
    order = models.IntegerField(default=0, verbose_name='정렬 순서')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'chat_folders'
        verbose_name = '채팅방 폴더'
        verbose_name_plural = '채팅방 폴더'
        ordering = ['order', 'created_at']
    
    def __str__(self):
        return f"{self.user.name}'s {self.name}"


class ChatFolderRoom(models.Model):
    """폴더-채팅방 연결 모델"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    folder = models.ForeignKey(ChatFolder, on_delete=models.CASCADE, related_name='rooms', verbose_name='폴더')
    room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name='folders', verbose_name='채팅방')
    order = models.IntegerField(default=0, verbose_name='정렬 순서')
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'chat_folder_rooms'
        verbose_name = '폴더-채팅방'
        verbose_name_plural = '폴더-채팅방'
        unique_together = [['folder', 'room']]
        ordering = ['order', 'created_at']
    
    def __str__(self):
        return f"{self.room} in {self.folder.name}"


class GroupChatInvitation(models.Model):
    """그룹챗 초대 모델"""
    STATUS_CHOICES = [
        ('pending', '대기중'),
        ('accepted', '수락됨'),
        ('rejected', '거절됨'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name='invitations', verbose_name='채팅방')
    inviter = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_invitations', verbose_name='초대자')
    invitee = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_invitations', verbose_name='초대받은 사람')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending', verbose_name='상태')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'group_chat_invitations'
        verbose_name = '그룹챗 초대'
        verbose_name_plural = '그룹챗 초대'
        unique_together = [['room', 'invitee']]
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['invitee', 'status']),
            models.Index(fields=['room', 'status']),
        ]
    
    def __str__(self):
        return f"{self.inviter.name} -> {self.invitee.name} ({self.room.name}) ({self.status})"
    
    def clean(self):
        """검증: 그룹챗만 초대 가능, 이미 멤버인 경우 초대 불가"""
        from django.core.exceptions import ValidationError
        
        if self.room.room_type != 'group':
            raise ValidationError('그룹챗에만 초대할 수 있습니다.')
        
        if ChatRoomMember.objects.filter(room=self.room, user=self.invitee).exists():
            raise ValidationError('이미 채팅방 멤버입니다.')
    
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
