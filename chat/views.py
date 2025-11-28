from typing import Optional, Tuple

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User

from .models import (
    ChatFolder,
    ChatFolderRoom,
    ChatRoom,
    ChatRoomMember,
    DirectChatInvitation,
    GroupChatInvitation,
    Message,
)

# MARK: - Helper Functions

def get_room_or_404(room_id) -> Tuple[Optional[ChatRoom], Optional[Response]]:
    """채팅방을 조회하거나 404 에러 응답을 반환하는 헬퍼 함수
    
    Args:
        room_id: 조회할 채팅방 ID
        
    Returns:
        tuple[ChatRoom, None] | tuple[None, Response]: 
            - 성공 시: (ChatRoom 객체, None)
            - 실패 시: (None, 404 Response)
    
    Usage:
        room, error = get_room_or_404(room_id)
        if error:
            return error
    """
    try:
        return ChatRoom.objects.get(id=room_id), None
    except ChatRoom.DoesNotExist:
        return None, Response(
            {'error': '채팅방을 찾을 수 없습니다.'},
            status=status.HTTP_404_NOT_FOUND
        )
from .response_serializers import (
    ChatRoomLeaveResponseSerializer,
    ChatRoomMemberAddResponseSerializer,
    ChatRoomMemberRemoveResponseSerializer,
    MessageListResponseSerializer,
    MessageReadResponseSerializer,
)
from .serializers import (
    ChatFolderCreateSerializer,
    ChatFolderRoomAddSerializer,
    ChatFolderRoomSerializer,
    ChatFolderSerializer,
    ChatFolderUpdateSerializer,
    ChatInvitationListSerializer,
    ChatRoomMemberAddSerializer,
    ChatRoomMemberSerializer,
    ChatRoomSerializer,
    ChatRoomUpdateSerializer,
    DirectChatCreateSerializer,
    DirectChatInvitationResponseSerializer,
    DirectChatInvitationSerializer,
    EmptySerializer,
    GroupChatCreateSerializer,
    GroupChatInvitationCreateSerializer,
    GroupChatInvitationResponseSerializer,
    GroupChatInvitationSerializer,
    MessageCreateSerializer,
    MessageReadSerializer,
    MessageSerializer,
    MessageUpdateSerializer,
    UserBasicSerializer,
)


class ChatRoomListView(APIView):
    """채팅방 목록 조회"""
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        tags=['Chat'],
        summary='채팅방 목록 조회',
        description='사용자가 참여한 모든 채팅방 목록을 조회합니다.',
        operation_id='chat_rooms_list',
        responses={
            200: ChatRoomSerializer(many=True),
        }
    )
    def get(self, request):
        """참여한 채팅방 목록 조회"""
        user = request.user
        
        # 사용자가 멤버로 참여한 채팅방 조회
        rooms = ChatRoom.objects.filter(
            members__user=user
        ).prefetch_related(
            Prefetch('members', queryset=ChatRoomMember.objects.select_related('user')),
            # 마지막 메시지만 가져오기 위해 to_attr 사용
            # 슬라이싱은 Prefetch 내부에서 불가능하므로, serializer에서 첫 번째만 사용
            Prefetch(
                'messages',
                queryset=Message.objects.select_related('sender', 'asset', 'reply_to', 'reply_to__sender')
                    .order_by('-created_at'),
                to_attr='last_message_list'
            ),
            # 폴더 정보 prefetch
            Prefetch(
                'folders',
                queryset=ChatFolderRoom.objects.filter(folder__user=user).select_related('folder'),
                to_attr='user_folder_rooms'
            )
        ).distinct().order_by('-updated_at')
        
        serializer = ChatRoomSerializer(rooms, many=True, context={'request': request})
        return Response(serializer.data)


class DirectChatCreateView(APIView):
    """1:1 채팅 생성"""
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = 'invitation'
    
    @extend_schema(
        tags=['Chat'],
        summary='1:1 채팅 초대 전송',
        description='1:1 채팅 초대를 전송합니다. 상대방이 수락해야 채팅방이 생성됩니다.',
        request=DirectChatCreateSerializer,
        responses={
            200: OpenApiResponse(description='기존 채팅방 반환'),
            201: OpenApiResponse(description='초대 전송 완료'),
            400: OpenApiResponse(description='잘못된 요청'),
        }
    )
    def post(self, request):
        """1:1 채팅 초대 전송"""
        serializer = DirectChatCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        other_user_id = serializer.validated_data['user_id']
        user = request.user
        
        # 자기 자신과는 채팅 불가
        if other_user_id == user.id:
            return Response(
                {'error': '자기 자신과는 1:1 채팅을 생성할 수 없습니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 상대방 사용자 확인
        try:
            other_user = User.objects.get(id=other_user_id)
        except User.DoesNotExist:
            return Response(
                {'error': '존재하지 않는 사용자입니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        with transaction.atomic():
            # 기존 1:1 채팅방 확인 (같은 두 사용자 조합이 하나만 존재하도록 보장)
            existing_room = ChatRoom.objects.filter(
                room_type='direct',
                members__user=user
            ).filter(
                members__user=other_user
            ).annotate(
                member_count=Count('members')
            ).filter(
                member_count=2
            ).distinct().first()
            
            if existing_room:
                # 기존 채팅방이 있으면 반환
                serializer = ChatRoomSerializer(existing_room, context={'request': request})
                return Response({
                    'message': '이미 채팅방이 존재합니다.',
                    'room': serializer.data
                }, status=status.HTTP_200_OK)
            
            # 이미 대기 중인 초대가 있는지 확인 (양방향 모두 체크)
            existing_invitation = DirectChatInvitation.objects.filter(
                Q(inviter=user, invitee=other_user, status='pending') |
                Q(inviter=other_user, invitee=user, status='pending')
            ).first()
            
            if existing_invitation:
                if existing_invitation.inviter == user:
                    # 기존 초대 객체를 시리얼라이즈하여 반환
                    invitation_serializer = DirectChatInvitationSerializer(existing_invitation, context={'request': request})
                    return Response(invitation_serializer.data, status=status.HTTP_200_OK)
                else:
                    # 상대방이 나에게 초대를 보낸 경우, 자동으로 수락하고 채팅방 생성
                    return self._accept_invitation(existing_invitation, request)
            
            # 1:1 채팅 생성 시 상대방의 공개키 확인
            if not other_user.public_key:
                return Response(
                    {'error': '상대방이 공개키를 등록하지 않았습니다. E2EE를 사용하려면 공개키가 필요합니다.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # 초대 생성
            invitation = DirectChatInvitation.objects.create(
                inviter=user,
                invitee=other_user
            )
            
            # TODO: 실시간 알림 전송 (WebSocket or Push Notification)
            
            # 초대 객체를 시리얼라이즈하여 반환
            invitation_serializer = DirectChatInvitationSerializer(invitation, context={'request': request})
            return Response(invitation_serializer.data, status=status.HTTP_201_CREATED)
    
    def _accept_invitation(self, invitation, request):
        """초대 수락 처리 (내부 헬퍼 메서드)"""
        with transaction.atomic():
            # 채팅방 생성
            room = ChatRoom.objects.create(
                room_type='direct',
                created_by=invitation.inviter
            )
            
            # 멤버 추가
            ChatRoomMember.objects.create(room=room, user=invitation.inviter, role='member')
            ChatRoomMember.objects.create(room=room, user=invitation.invitee, role='member')
            
            # 초대 상태 업데이트
            invitation.room = room
            invitation.status = 'accepted'
            invitation.save()
            
            serializer = ChatRoomSerializer(room, context={'request': request})
            return Response({
                'message': '초대를 수락했습니다.',
                'room': serializer.data
            }, status=status.HTTP_201_CREATED)


class GroupChatCreateView(APIView):
    """그룹 채팅 생성"""
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = 'invitation'
    
    @extend_schema(
        tags=['Chat'],
        summary='그룹 채팅 생성 및 초대',
        description='새로운 그룹 채팅방을 생성하고 멤버들에게 초대를 전송합니다.',
        request=GroupChatCreateSerializer,
        responses={
            201: ChatRoomSerializer,
            400: OpenApiResponse(description='잘못된 요청'),
        }
    )
    def post(self, request):
        """그룹 채팅 생성 및 초대"""
        serializer = GroupChatCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        name = serializer.validated_data['name']
        description = serializer.validated_data.get('description')
        member_ids = serializer.validated_data.get('member_ids', [])
        user = request.user
        
        # 그룹 채팅방 생성
        room = ChatRoom.objects.create(
            room_type='group',
            name=name,
            description=description,
            created_by=user
        )
        
        # 생성자를 방장으로 추가 (자동 승인)
        ChatRoomMember.objects.create(room=room, user=user, role='owner')
        
        # 다른 멤버들에게 초대 전송
        invited_count = 0
        for member_id in member_ids:
            if member_id != user.id:
                try:
                    member_user = User.objects.get(id=member_id)
                    # 초대 생성
                    GroupChatInvitation.objects.get_or_create(
                        room=room,
                        inviter=user,
                        invitee=member_user,
                        defaults={'status': 'pending'}
                    )
                    invited_count += 1
                except User.DoesNotExist:
                    continue
        
        # TODO: 실시간 알림 전송 (WebSocket or Push Notification)
        
        serializer = ChatRoomSerializer(room, context={'request': request})
        return Response({
            'message': f'그룹 채팅방을 생성하고 {invited_count}명에게 초대를 전송했습니다.',
            'room': serializer.data
        }, status=status.HTTP_201_CREATED)


class ChatRoomDetailView(APIView):
    """채팅방 상세 조회 및 수정"""
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        tags=['Chat'],
        summary='채팅방 상세 조회',
        description='채팅방의 상세 정보를 조회합니다.',
        operation_id='chat_rooms_detail',
        responses={
            200: ChatRoomSerializer,
            404: OpenApiResponse(description='채팅방을 찾을 수 없음'),
        }
    )
    def get(self, request, room_id):
        """채팅방 상세 조회"""
        try:
            room = ChatRoom.objects.prefetch_related(
                Prefetch('members', queryset=ChatRoomMember.objects.select_related('user'))
            ).get(id=room_id)
        except ChatRoom.DoesNotExist:
            return Response(
                {'error': '채팅방을 찾을 수 없습니다.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # 멤버인지 확인
        if not ChatRoomMember.objects.filter(room=room, user=request.user).exists():
            return Response(
                {'error': '채팅방 멤버가 아닙니다.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = ChatRoomSerializer(room, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        tags=['Chat'],
        summary='채팅방 정보 수정',
        description='그룹 채팅방의 이름과 설명을 수정합니다.',
        request=ChatRoomUpdateSerializer,
        responses={
            200: ChatRoomSerializer,
            403: OpenApiResponse(description='권한 없음'),
            404: OpenApiResponse(description='채팅방을 찾을 수 없음'),
        }
    )
    def patch(self, request, room_id):
        """채팅방 정보 수정"""
        room, error = get_room_or_404(room_id)
        if error:
            return error
        
        # 권한 확인 (방장 또는 관리자만 수정 가능)
        member = ChatRoomMember.objects.filter(room=room, user=request.user).first()
        if not member or member.role not in ['owner', 'admin']:
            return Response(
                {'error': '채팅방 정보를 수정할 권한이 없습니다.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # 1:1 채팅은 수정 불가
        if room.room_type == 'direct':
            return Response(
                {'error': '1:1 채팅방은 수정할 수 없습니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 정보 수정
        name = request.data.get('name')
        description = request.data.get('description')
        
        if name:
            room.name = name
        if description is not None:
            room.description = description
        
        room.save()
        
        serializer = ChatRoomSerializer(room, context={'request': request})
        return Response(serializer.data)


class MessageListView(APIView):
    """메시지 목록 조회 및 전송"""
    permission_classes = [permissions.IsAuthenticated]
    
    def get_throttles(self):
        """POST 요청(메시지 전송)에만 별도의 속도 제한 적용"""
        if self.request.method == 'POST':
            self.throttle_scope = 'chat_action'
        else:
            self.throttle_scope = None
        return super().get_throttles()
    
    @extend_schema(
        tags=['Chat'],
        summary='메시지 목록 조회',
        description='채팅방의 메시지 목록을 조회합니다.',
        parameters=[
            OpenApiParameter(
                name='page',
                type=int,
                location=OpenApiParameter.QUERY,
                description='페이지 번호',
                required=False,
                default=1
            ),
            OpenApiParameter(
                name='page_size',
                type=int,
                location=OpenApiParameter.QUERY,
                description='페이지당 메시지 수',
                required=False,
                default=50
            ),
        ],
        responses={
            200: MessageListResponseSerializer,
            404: OpenApiResponse(description='채팅방을 찾을 수 없음'),
        }
    )
    def get(self, request, room_id):
        """메시지 목록 조회"""
        room, error = get_room_or_404(room_id)
        if error:
            return error
        
        # 멤버인지 확인
        if not ChatRoomMember.objects.filter(room=room, user=request.user).exists():
            return Response(
                {'error': '채팅방 멤버가 아닙니다.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # 페이지네이션
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 50))
        offset = (page - 1) * page_size
        
        # 메시지 조회 (최신순)
        messages = Message.objects.filter(room=room).select_related(
            'sender', 'reply_to', 'reply_to__sender', 'asset'
        ).order_by('-created_at')[offset:offset + page_size]
        
        serializer = MessageSerializer(list(reversed(messages)), many=True)
        total = Message.objects.filter(room=room).count()
        has_next = (page * page_size) < total
        
        return Response({
            'results': serializer.data,
            'page': page,
            'page_size': page_size,
            'total': total,
            'has_next': has_next
        })
    
    @extend_schema(
        tags=['Chat'],
        summary='메시지 전송',
        description='채팅방에 메시지를 전송합니다.',
        request=MessageCreateSerializer,
        responses={
            201: MessageSerializer,
            400: OpenApiResponse(description='잘못된 요청'),
            404: OpenApiResponse(description='채팅방을 찾을 수 없음'),
        }
    )
    def post(self, request, room_id):
        """메시지 전송"""
        room, error = get_room_or_404(room_id)
        if error:
            return error
        
        # 멤버인지 확인
        if not ChatRoomMember.objects.filter(room=room, user=request.user).exists():
            return Response(
                {'error': '채팅방 멤버가 아닙니다.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = MessageCreateSerializer(
            data={**request.data, 'room': room_id},
            context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        message = serializer.save()
        
        # 채팅방 업데이트 시간 갱신
        room.save(update_fields=['updated_at'])
        
        serializer = MessageSerializer(message)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class MessageDetailView(APIView):
    """메시지 수정 및 삭제"""
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = 'chat_action'

    @extend_schema(
        tags=['Chat'],
        summary='메시지 수정',
        description='메시지를 수정합니다. 본인이 작성한 메시지만 수정할 수 있습니다. 텍스트 메시지만 수정 가능합니다.',
        request=MessageUpdateSerializer,
        responses={
            200: MessageSerializer,
            403: OpenApiResponse(description='권한 없음'),
            404: OpenApiResponse(description='메시지를 찾을 수 없음'),
        }
    )
    def patch(self, request, room_id, message_id):
        """메시지 수정"""
        try:
            message = Message.objects.select_related('sender', 'room').get(id=message_id, room_id=room_id)
        except Message.DoesNotExist:
            return Response(
                {'error': '메시지를 찾을 수 없습니다.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # 본인 확인
        if message.sender != request.user:
            return Response(
                {'error': '본인이 작성한 메시지만 수정할 수 있습니다.'},
                status=status.HTTP_403_FORBIDDEN
            )
            
        # 텍스트 메시지만 수정 가능 (이미지 등은 불가 정책)
        if message.message_type != 'text':
             return Response(
                {'error': '텍스트 메시지만 수정할 수 있습니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = MessageUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        if message.room.room_type == 'direct':
            if not serializer.validated_data.get('encrypted_content'):
                 return Response(
                    {'error': '1:1 채팅에서는 암호화된 내용이 필수입니다.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            message.encrypted_content = serializer.validated_data['encrypted_content']
            
            # 암호화 키도 함께 업데이트 (클라이언트가 제공한 경우)
            if 'encrypted_session_key' in serializer.validated_data:
                message.encrypted_session_key = serializer.validated_data['encrypted_session_key']
            if 'self_encrypted_session_key' in serializer.validated_data:
                message.self_encrypted_session_key = serializer.validated_data['self_encrypted_session_key']
        else:
            if not serializer.validated_data.get('content'):
                 return Response(
                    {'error': '그룹 채팅에서는 내용이 필수입니다.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            message.content = serializer.validated_data['content']
            
        message.save()
        
        # 웹소켓으로 메시지 수정 알림 전송
        channel_layer = get_channel_layer()
        room_group_name = f'chat_{room_id}'
        
        message_data = MessageSerializer(message).data
        
        async_to_sync(channel_layer.group_send)(
            room_group_name,
            {
                'type': 'message_update',
                'message': message_data
            }
        )
        
        return Response(message_data)

    @extend_schema(
        tags=['Chat'],
        summary='메시지 삭제',
        description='메시지를 삭제합니다. 본인이 작성한 메시지만 삭제할 수 있습니다.',
        responses={
            204: OpenApiResponse(description='삭제 성공'),
            403: OpenApiResponse(description='권한 없음'),
            404: OpenApiResponse(description='메시지를 찾을 수 없음'),
        }
    )
    def delete(self, request, room_id, message_id):
        """메시지 삭제"""
        try:
            message = Message.objects.select_related('sender', 'room').get(id=message_id, room_id=room_id)
        except Message.DoesNotExist:
            return Response(
                {'error': '메시지를 찾을 수 없습니다.'},
                status=status.HTTP_404_NOT_FOUND
            )
            
        # 본인 확인
        if message.sender != request.user:
            return Response(
                {'error': '본인이 작성한 메시지만 삭제할 수 있습니다.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # 삭제 전에 메시지 ID 저장
        message_id_to_delete = message.id
        
        # 웹소켓으로 메시지 삭제 알림 전송 (삭제 전에 전송)
        channel_layer = get_channel_layer()
        room_group_name = f'chat_{room_id}'
        
        async_to_sync(channel_layer.group_send)(
            room_group_name,
            {
                'type': 'message_delete',
                'message_id': str(message_id_to_delete)
            }
        )
            
        message.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MessageReadView(APIView):
    """메시지 읽음 처리 뷰"""
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        tags=['Chat'],
        summary='메시지 읽음 처리',
        description='메시지를 읽음 처리합니다. 여러 메시지를 한 번에 읽음 처리할 수 있습니다.',
        request=MessageReadSerializer,
        responses={
            200: MessageReadResponseSerializer,
            404: OpenApiResponse(description='채팅방을 찾을 수 없음'),
        }
    )
    def post(self, request, room_id):
        """메시지 읽음 처리"""
        room, error = get_room_or_404(room_id)
        if error:
            return error
        
        # 멤버인지 확인
        if not ChatRoomMember.objects.filter(room=room, user=request.user).exists():
            return Response(
                {'error': '채팅방 멤버가 아닙니다.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        message_ids = request.data.get('message_ids', [])
        if not message_ids:
            return Response(
                {'error': '읽음 처리할 메시지 ID 리스트가 필요합니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 해당 채팅방의 메시지만 읽음 처리
        read_count = Message.objects.filter(
            id__in=message_ids,
            room=room
        ).exclude(sender=request.user).update(is_read=True)
        
        # 마지막 읽은 시간 업데이트
        ChatRoomMember.objects.filter(
            room=room,
            user=request.user
        ).update(last_read_at=timezone.now())
        
        # 웹소켓으로 읽음 처리 알림 전송
        if read_count > 0:
            channel_layer = get_channel_layer()
            room_group_name = f'chat_{room_id}'
            
            async_to_sync(channel_layer.group_send)(
                room_group_name,
                {
                    'type': 'read_receipt',
                    'user_id': str(request.user.id),
                    'message_ids': message_ids
                }
            )
        
        return Response({
            'message': f'{read_count}개의 메시지를 읽음 처리했습니다.',
            'read_count': read_count
        }, status=status.HTTP_200_OK)


class ChatRoomLeaveView(APIView):
    """채팅방 나가기 뷰"""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EmptySerializer
    
    @extend_schema(
        tags=['Chat'],
        summary='채팅방 나가기',
        description='채팅방을 나갑니다. 1:1 채팅의 경우 채팅방이 삭제되고, 그룹 채팅의 경우 본인만 나갑니다.',
        request=None,
        responses={
            200: ChatRoomLeaveResponseSerializer,
            404: OpenApiResponse(description='채팅방을 찾을 수 없음'),
        }
    )
    def post(self, request, room_id):
        """채팅방 나가기"""
        room, error = get_room_or_404(room_id)
        if error:
            return error
        
        # 멤버인지 확인
        member = ChatRoomMember.objects.filter(room=room, user=request.user).first()
        if not member:
            return Response(
                {'error': '채팅방 멤버가 아닙니다.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # 1:1 채팅인 경우 채팅방 삭제
        if room.room_type == 'direct':
            room.delete()
            return Response({
                'message': '채팅방이 삭제되었습니다.'
            }, status=status.HTTP_200_OK)
        
        # 그룹 채팅인 경우 본인만 나가기
        # 방장인 경우 방장 권한을 다른 멤버에게 양도하거나 채팅방 삭제
        if member.role == 'owner':
            # 다른 멤버가 있으면 관리자 중 한 명에게 권한 양도
            admin_member = ChatRoomMember.objects.filter(
                room=room,
                role='admin'
            ).exclude(user=request.user).first()
            
            if admin_member:
                admin_member.role = 'owner'
                admin_member.save()
            else:
                # 관리자도 없으면 일반 멤버 중 한 명에게 권한 양도
                regular_member = ChatRoomMember.objects.filter(
                    room=room
                ).exclude(user=request.user).first()
                
                if regular_member:
                    regular_member.role = 'owner'
                    regular_member.save()
                else:
                    # 마지막 멤버인 경우 채팅방 삭제
                    room.delete()
                    return Response({
                        'message': '마지막 멤버였으므로 채팅방이 삭제되었습니다.'
                    }, status=status.HTTP_200_OK)
        
        member.delete()
        return Response({
            'message': '채팅방을 나갔습니다.'
        }, status=status.HTTP_200_OK)


class ChatFolderListView(APIView):
    """채팅방 폴더 목록 조회 및 생성"""
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        tags=['Chat'],
        summary='폴더 목록 조회',
        description='사용자의 채팅방 폴더 목록을 조회합니다.',
        operation_id='chat_folders_list',
        responses={
            200: ChatFolderSerializer(many=True),
        }
    )
    def get(self, request):
        """폴더 목록 조회"""
        folders = ChatFolder.objects.filter(user=request.user).prefetch_related('rooms__room')
        serializer = ChatFolderSerializer(folders, many=True)
        return Response(serializer.data)
    
    @extend_schema(
        tags=['Chat'],
        summary='폴더 생성',
        description='새로운 채팅방 폴더를 생성합니다.',
        request=ChatFolderCreateSerializer,
        responses={
            201: ChatFolderSerializer,
            400: OpenApiResponse(description='잘못된 요청'),
        }
    )
    def post(self, request):
        """폴더 생성"""
        name = request.data.get('name')
        color = request.data.get('color', '#000000')
        icon = request.data.get('icon', 'folder.fill')
        
        if not name:
            return Response(
                {'error': '폴더 이름은 필수입니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        folder = ChatFolder.objects.create(
            user=request.user,
            name=name,
            color=color,
            icon=icon
        )
        
        serializer = ChatFolderSerializer(folder)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class ChatFolderDetailView(APIView):
    """폴더 상세 조회 및 수정/삭제"""
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        tags=['Chat'],
        summary='폴더 상세 조회',
        description='폴더의 상세 정보와 포함된 채팅방 목록을 조회합니다.',
        operation_id='chat_folders_detail',
        responses={
            200: ChatFolderRoomSerializer(many=True),
            404: OpenApiResponse(description='폴더를 찾을 수 없음'),
        }
    )
    def get(self, request, folder_id):
        """폴더 상세 조회"""
        try:
            folder = ChatFolder.objects.get(id=folder_id, user=request.user)
        except ChatFolder.DoesNotExist:
            return Response(
                {'error': '폴더를 찾을 수 없습니다.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        folder_rooms = ChatFolderRoom.objects.filter(folder=folder).prefetch_related('room__members__user')
        serializer = ChatFolderRoomSerializer(folder_rooms, many=True, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        tags=['Chat'],
        summary='폴더 수정',
        description='폴더의 이름과 색상을 수정합니다.',
        request=ChatFolderUpdateSerializer,
        responses={
            200: ChatFolderSerializer,
            404: OpenApiResponse(description='폴더를 찾을 수 없음'),
        }
    )
    def patch(self, request, folder_id):
        """폴더 수정"""
        try:
            folder = ChatFolder.objects.get(id=folder_id, user=request.user)
        except ChatFolder.DoesNotExist:
            return Response(
                {'error': '폴더를 찾을 수 없습니다.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        name = request.data.get('name')
        color = request.data.get('color')
        icon = request.data.get('icon')
        
        if name:
            folder.name = name
        if color:
            folder.color = color
        if icon:
            folder.icon = icon
        
        folder.save()
        
        serializer = ChatFolderSerializer(folder)
        return Response(serializer.data)
    
    @extend_schema(
        tags=['Chat'],
        summary='폴더 삭제',
        description='폴더를 삭제합니다. 폴더에 포함된 채팅방은 삭제되지 않습니다.',
        request=None,
        responses={
            204: OpenApiResponse(description='삭제 성공'),
            404: OpenApiResponse(description='폴더를 찾을 수 없음'),
        }
    )
    def delete(self, request, folder_id):
        """폴더 삭제"""
        try:
            folder = ChatFolder.objects.get(id=folder_id, user=request.user)
        except ChatFolder.DoesNotExist:
            return Response(
                {'error': '폴더를 찾을 수 없습니다.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        folder.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ChatFolderRoomView(APIView):
    """폴더에 채팅방 추가/제거"""
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        tags=['Chat'],
        summary='폴더에 채팅방 추가',
        description='채팅방을 폴더에 추가합니다.',
        operation_id='chat_folders_rooms_add',
        request=ChatFolderRoomAddSerializer,
        responses={
            201: ChatFolderRoomSerializer,
            400: OpenApiResponse(description='잘못된 요청'),
            404: OpenApiResponse(description='폴더 또는 채팅방을 찾을 수 없음'),
        }
    )
    def post(self, request, folder_id):
        """폴더에 채팅방 추가"""
        try:
            folder = ChatFolder.objects.get(id=folder_id, user=request.user)
        except ChatFolder.DoesNotExist:
            return Response(
                {'error': '폴더를 찾을 수 없습니다.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        room_id = request.data.get('room_id')
        if not room_id:
            return Response(
                {'error': 'room_id는 필수입니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        room, error = get_room_or_404(room_id)
        if error:
            return error
        
        # 채팅방 멤버인지 확인
        if not ChatRoomMember.objects.filter(room=room, user=request.user).exists():
            return Response(
                {'error': '채팅방 멤버가 아닙니다.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # 이미 폴더에 있는지 확인
        folder_room, created = ChatFolderRoom.objects.get_or_create(
            folder=folder,
            room=room,
            defaults={'order': folder.rooms.count()}
        )
        
        if not created:
            return Response(
                {'error': '이미 폴더에 포함된 채팅방입니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        serializer = ChatFolderRoomSerializer(folder_room, context={'request': request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    @extend_schema(
        tags=['Chat'],
        summary='폴더에서 채팅방 제거',
        description='폴더에서 채팅방을 제거합니다. 채팅방 자체는 삭제되지 않습니다.',
        operation_id='chat_folders_rooms_remove',
        request=None,
        responses={
            204: OpenApiResponse(description='제거 성공'),
            404: OpenApiResponse(description='폴더 또는 채팅방을 찾을 수 없음'),
        }
    )
    def delete(self, request, folder_id, room_id):
        """폴더에서 채팅방 제거"""
        try:
            folder = ChatFolder.objects.get(id=folder_id, user=request.user)
        except ChatFolder.DoesNotExist:
            return Response(
                {'error': '폴더를 찾을 수 없습니다.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        try:
            folder_room = ChatFolderRoom.objects.get(folder=folder, room_id=room_id)
        except ChatFolderRoom.DoesNotExist:
            return Response(
                {'error': '폴더에 해당 채팅방이 없습니다.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        folder_room.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ChatRoomMemberView(APIView):
    """채팅방 멤버 관리 뷰"""
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        tags=['Chat'],
        summary='채팅방 멤버 추가',
        description='그룹 채팅방에 멤버를 추가합니다. (방장 또는 관리자만 가능)',
        operation_id='chat_rooms_members_add',
        request=ChatRoomMemberAddSerializer,
        responses={
            200: ChatRoomMemberAddResponseSerializer,
            403: OpenApiResponse(description='권한 없음'),
            404: OpenApiResponse(description='채팅방을 찾을 수 없음'),
        }
    )
    def post(self, request, room_id):
        """채팅방 멤버 추가"""
        room, error = get_room_or_404(room_id)
        if error:
            return error
        
        # 1:1 채팅은 멤버 추가 불가
        if room.room_type == 'direct':
            return Response(
                {'error': '1:1 채팅방에는 멤버를 추가할 수 없습니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 권한 확인 (방장 또는 관리자만 추가 가능)
        member = ChatRoomMember.objects.filter(room=room, user=request.user).first()
        if not member or member.role not in ['owner', 'admin']:
            return Response(
                {'error': '멤버를 추가할 권한이 없습니다.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        user_ids = request.data.get('user_ids', [])
        if not user_ids:
            return Response(
                {'error': '추가할 사용자 ID 리스트가 필요합니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        added_members = []
        for user_id in user_ids:
            try:
                user_to_add = User.objects.get(id=user_id)
                # 이미 멤버인지 확인
                if ChatRoomMember.objects.filter(room=room, user=user_to_add).exists():
                    continue
                
                # 멤버 추가
                new_member = ChatRoomMember.objects.create(
                    room=room,
                    user=user_to_add,
                    role='member'
                )
                added_members.append(new_member)
            except User.DoesNotExist:
                continue
        
        serializer = ChatRoomMemberSerializer(added_members, many=True)
        return Response({
            'message': f'{len(added_members)}명의 멤버가 추가되었습니다.',
            'added_members': serializer.data
        }, status=status.HTTP_200_OK)
    
    @extend_schema(
        tags=['Chat'],
        summary='채팅방 멤버 제거',
        description='그룹 채팅방에서 멤버를 제거합니다. (방장 또는 관리자만 가능, 본인은 나가기)',
        operation_id='chat_rooms_members_remove',
        request=None,
        responses={
            200: ChatRoomMemberRemoveResponseSerializer,
            403: OpenApiResponse(description='권한 없음'),
            404: OpenApiResponse(description='채팅방 또는 멤버를 찾을 수 없음'),
        }
    )
    def delete(self, request, room_id, user_id):
        """채팅방 멤버 제거"""
        room, error = get_room_or_404(room_id)
        if error:
            return error
        
        # 1:1 채팅은 멤버 제거 불가 (채팅방 나가기는 채팅방 삭제로 처리)
        if room.room_type == 'direct':
            return Response(
                {'error': '1:1 채팅방에서는 멤버를 제거할 수 없습니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # user_id가 현재 사용자와 같으면 본인 나가기
        if user_id == request.user.id:
            # 본인 나가기 로직 (ChatRoomLeaveView와 동일)
            member = ChatRoomMember.objects.get(room=room, user=request.user)
            member.delete()
            
            # 방장이 나가면 다른 멤버에게 방장 권한 이전
            if room.created_by == request.user:
                remaining_members = ChatRoomMember.objects.filter(room=room).exclude(user=request.user)
                if remaining_members.exists():
                    new_owner = remaining_members.first().user
                    room.created_by = new_owner
                    room.save()
            
            return Response({
                'message': '채팅방을 나갔습니다.'
            }, status=status.HTTP_200_OK)
        
        # 다른 멤버 제거 (방장 또는 관리자만 가능)
        try:
            member_to_remove = ChatRoomMember.objects.get(room=room, user_id=user_id)
        except ChatRoomMember.DoesNotExist:
            return Response(
                {'error': '멤버를 찾을 수 없습니다.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # 본인 나가기인 경우
        if member_to_remove.user == request.user:
            member_to_remove.delete()
            return Response({
                'message': '채팅방을 나갔습니다.'
            }, status=status.HTTP_200_OK)
        
        # 다른 멤버 제거인 경우 권한 확인
        member = ChatRoomMember.objects.filter(room=room, user=request.user).first()
        if not member or member.role not in ['owner', 'admin']:
            return Response(
                {'error': '멤버를 제거할 권한이 없습니다.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # 방장은 제거할 수 없음
        if member_to_remove.role == 'owner':
            return Response(
                {'error': '방장은 제거할 수 없습니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        member_to_remove.delete()
        return Response({
            'message': '멤버가 제거되었습니다.'
        }, status=status.HTTP_200_OK)


class GroupChatInvitationView(APIView):
    """그룹챗 초대 보내기"""
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = 'invitation'
    
    @extend_schema(
        tags=['Chat'],
        summary='그룹챗 초대 보내기',
        description='친구에게 그룹챗 초대를 보냅니다. 친구만 초대할 수 있습니다.',
        request=GroupChatInvitationCreateSerializer,
        responses={
            201: GroupChatInvitationSerializer,
            400: OpenApiResponse(description='잘못된 요청'),
            403: OpenApiResponse(description='권한 없음'),
            404: OpenApiResponse(description='채팅방 또는 사용자를 찾을 수 없음'),
        }
    )
    def post(self, request, room_id):
        """그룹챗 초대 보내기"""
        serializer = GroupChatInvitationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        user_id = serializer.validated_data['user_id']
        user = request.user
        
        room, error = get_room_or_404(room_id)
        if error:
            return error
        
        # 그룹챗만 초대 가능
        if room.room_type != 'group':
            return Response(
                {'error': '그룹챗에만 초대할 수 있습니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 채팅방 멤버인지 확인 (방장 또는 관리자만 초대 가능)
        member = ChatRoomMember.objects.filter(room=room, user=user).first()
        if not member or member.role not in ['owner', 'admin']:
            return Response(
                {'error': '그룹챗 초대 권한이 없습니다. 방장 또는 관리자만 초대할 수 있습니다.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # 초대받을 사용자 확인
        try:
            invitee = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response(
                {'error': '사용자를 찾을 수 없습니다.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # 자기 자신에게 초대 불가
        if invitee == user:
            return Response(
                {'error': '자기 자신에게 초대를 보낼 수 없습니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 이미 멤버인지 확인
        if ChatRoomMember.objects.filter(room=room, user=invitee).exists():
            return Response(
                {'error': '이미 채팅방 멤버입니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 친구인지 확인
        from friends.models import Friend
        is_friend = Friend.objects.filter(
            Q(requester=user, receiver=invitee) | Q(requester=invitee, receiver=user),
            status='accepted'
        ).exists()
        
        if not is_friend:
            return Response(
                {'error': '친구에게만 초대할 수 있습니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 이미 초대가 있는지 확인
        existing_invitation = GroupChatInvitation.objects.filter(
            room=room,
            invitee=invitee,
            status='pending'
        ).first()
        
        if existing_invitation:
            return Response(
                {'error': '이미 초대 요청이 대기 중입니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 새 초대 생성
        invitation = GroupChatInvitation.objects.create(
            room=room,
            inviter=user,
            invitee=invitee,
            status='pending'
        )
        
        # room과 members를 prefetch하여 직렬화
        invitation = GroupChatInvitation.objects.select_related(
            'room', 'inviter', 'invitee'
        ).prefetch_related(
            Prefetch('room__members', queryset=ChatRoomMember.objects.select_related('user'))
        ).get(id=invitation.id)
        
        serializer = GroupChatInvitationSerializer(invitation, context={'request': request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class GroupChatInvitationListView(APIView):
    """받은 그룹챗 초대 목록 조회"""
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        tags=['Chat'],
        summary='받은 그룹챗 초대 목록 조회',
        description='내가 받은 그룹챗 초대 목록을 조회합니다.',
        responses={
            200: GroupChatInvitationSerializer(many=True),
        }
    )
    def get(self, request):
        """받은 그룹챗 초대 목록 조회"""
        user = request.user
        
        # 받은 초대 중 대기 중인 것만 조회
        invitations = GroupChatInvitation.objects.filter(
            invitee=user,
            status='pending'
        ).select_related('room', 'inviter', 'invitee').prefetch_related(
            Prefetch('room__members', queryset=ChatRoomMember.objects.select_related('user'))
        ).order_by('-created_at')
        
        serializer = GroupChatInvitationSerializer(invitations, many=True, context={'request': request})
        return Response(serializer.data)


class GroupChatInvitationResponseView(APIView):
    """그룹챗 초대 수락/거절"""
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = 'invitation'
    
    @extend_schema(
        tags=['Chat'],
        summary='그룹챗 초대 수락/거절',
        description='받은 그룹챗 초대를 수락하거나 거절합니다. 수락 시 채팅방에 자동으로 추가됩니다.',
        request=GroupChatInvitationResponseSerializer,
        responses={
            200: GroupChatInvitationSerializer,
            404: OpenApiResponse(description='초대를 찾을 수 없음'),
        }
    )
    def post(self, request, invitation_id):
        """그룹챗 초대 수락/거절"""
        serializer = GroupChatInvitationResponseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        action = serializer.validated_data['action']
        user = request.user
        
        try:
            invitation = GroupChatInvitation.objects.select_related(
                'room', 'inviter', 'invitee'
            ).prefetch_related(
                Prefetch('room__members', queryset=ChatRoomMember.objects.select_related('user'))
            ).get(id=invitation_id, invitee=user, status='pending')
        except GroupChatInvitation.DoesNotExist:
            return Response(
                {'error': '초대를 찾을 수 없습니다.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        if action == 'accept':
            with transaction.atomic():
                # 초대 수락 시 채팅방에 멤버로 추가
                invitation.status = 'accepted'
                invitation.save()
                
                # 채팅방 멤버로 추가
                ChatRoomMember.objects.get_or_create(
                    room=invitation.room,
                    user=user,
                    defaults={'role': 'member'}
                )
                
                # room을 다시 조회하여 최신 members 정보 가져오기
                invitation.room = ChatRoom.objects.prefetch_related(
                    Prefetch('members', queryset=ChatRoomMember.objects.select_related('user'))
                ).get(id=invitation.room.id)
        else:
            # 초대 거절
            invitation.status = 'rejected'
            invitation.save()
        
        serializer = GroupChatInvitationSerializer(invitation, context={'request': request})
        return Response(serializer.data)


class DirectChatInvitationResponseView(APIView):
    """1:1 채팅 초대 수락/거절"""
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = 'invitation'
    
    @extend_schema(
        tags=['Chat'],
        summary='1:1 채팅 초대 수락/거절',
        description='받은 1:1 채팅 초대를 수락하거나 거절합니다. 수락 시 채팅방이 생성됩니다.',
        request=DirectChatInvitationResponseSerializer,
        responses={
            200: ChatRoomSerializer,  # 수락 시 생성된 채팅방 반환
            404: OpenApiResponse(description='초대를 찾을 수 없음'),
        }
    )
    def post(self, request, invitation_id):
        """1:1 채팅 초대 수락/거절"""
        serializer = DirectChatInvitationResponseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        action = serializer.validated_data['action']
        user = request.user
        
        try:
            invitation = DirectChatInvitation.objects.select_related('inviter', 'invitee').get(
                id=invitation_id, 
                invitee=user, 
                status='pending'
            )
        except DirectChatInvitation.DoesNotExist:
            return Response(
                {'error': '초대를 찾을 수 없습니다.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        if action == 'accept':
            with transaction.atomic():
                # 초대 수락 시 1:1 채팅방 생성
                invitation.status = 'accepted'
                invitation.save()
                
                # 1:1 채팅방 생성
                room = ChatRoom.objects.create(
                    room_type='direct',
                    created_by=invitation.inviter
                )
                
                # 초대자와 초대받은 사람 모두 멤버로 추가
                ChatRoomMember.objects.create(room=room, user=invitation.inviter, role='member')
                ChatRoomMember.objects.create(room=room, user=invitation.invitee, role='member')
                
                # 생성된 채팅방 조회 (members prefetch)
                room = ChatRoom.objects.prefetch_related(
                    Prefetch('members', queryset=ChatRoomMember.objects.select_related('user'))
                ).get(id=room.id)
                
                # 생성된 채팅방 반환
                room_serializer = ChatRoomSerializer(room, context={'request': request})
                return Response(room_serializer.data, status=status.HTTP_201_CREATED)
        else:
            # 초대 거절
            invitation.status = 'rejected'
            invitation.save()
            
            invitation_serializer = DirectChatInvitationSerializer(invitation, context={'request': request})
            return Response(invitation_serializer.data)


class DirectChatInvitationListView(APIView):
    """1:1 채팅 초대 목록 조회"""
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        tags=['Chat'],
        summary='1:1 채팅 초대 목록 조회',
        description='내가 받은 1:1 채팅 초대 목록을 조회합니다. (대기 중인 초대만)',
        responses={
            200: DirectChatInvitationSerializer(many=True),
        }
    )
    def get(self, request):
        """받은 1:1 채팅 초대 목록 조회"""
        user = request.user
        
        # 대기 중인 초대만 조회
        invitations = DirectChatInvitation.objects.filter(
            invitee=user,
            status='pending'
        ).select_related('inviter', 'invitee').order_by('-created_at')
        
        serializer = DirectChatInvitationSerializer(invitations, many=True, context={'request': request})
        return Response(serializer.data)


class AllChatInvitationListView(APIView):
    """통합 채팅 초대 목록 조회 (1:1 + 그룹)"""
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        tags=['Chat'],
        summary='통합 채팅 초대 목록 조회',
        description='내가 받은 모든 채팅 초대 목록을 조회합니다. (1:1 채팅 + 그룹 채팅, 대기 중인 초대만)',
        parameters=[
            OpenApiParameter(
                name='page',
                type=int,
                location=OpenApiParameter.QUERY,
                description='페이지 번호',
                required=False,
                default=1
            ),
            OpenApiParameter(
                name='page_size',
                type=int,
                location=OpenApiParameter.QUERY,
                description='페이지당 초대 수',
                required=False,
                default=20
            ),
        ],
        responses={
            200: ChatInvitationListSerializer(many=True),
        }
    )
    def get(self, request):
        """받은 모든 채팅 초대 목록 조회 (1:1 + 그룹)"""
        user = request.user
        
        # 페이지네이션 파라미터
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 20))
        offset = (page - 1) * page_size
        
        # 1:1 채팅 초대 조회
        direct_invitations = DirectChatInvitation.objects.filter(
            invitee=user,
            status='pending'
        ).select_related('inviter', 'invitee')
        
        # 그룹 채팅 초대 조회
        group_invitations = GroupChatInvitation.objects.filter(
            invitee=user,
            status='pending'
        ).select_related('room', 'inviter', 'invitee').prefetch_related(
            Prefetch('room__members', queryset=ChatRoomMember.objects.select_related('user'))
        )
        
        # 통합 리스트 생성
        invitation_data = []
        
        # 1:1 채팅 초대 데이터 구성
        for invitation in direct_invitations:
            invitation_data.append({
                'id': invitation.id,
                'type': 'direct',
                'inviter': invitation.inviter,  # User 객체를 직접 전달
                'invitee': invitation.invitee,  # User 객체를 직접 전달
                'room': None,
                'status': invitation.status,
                'created_at': invitation.created_at,
                'updated_at': invitation.updated_at,
            })
        
        # 그룹 채팅 초대 데이터 구성
        for invitation in group_invitations:
            invitation_data.append({
                'id': invitation.id,
                'type': 'group',
                'inviter': invitation.inviter,  # User 객체를 직접 전달
                'invitee': invitation.invitee,  # User 객체를 직접 전달
                'room': invitation.room,  # ChatRoom 객체를 직접 전달
                'status': invitation.status,
                'created_at': invitation.created_at,
                'updated_at': invitation.updated_at,
            })
        
        # 생성 시간 기준으로 정렬 (최신순)
        invitation_data.sort(key=lambda x: x['created_at'], reverse=True)
        
        # 페이지네이션 적용
        total = len(invitation_data)
        paginated_data = invitation_data[offset:offset + page_size]
        has_next = (page * page_size) < total
        
        # 시리얼라이저에 context 전달 (ChatRoomSerializer가 request를 필요로 함)
        serializer = ChatInvitationListSerializer(paginated_data, many=True, context={'request': request})
        return Response({
            'results': serializer.data,
            'page': page,
            'page_size': page_size,
            'total': total,
            'has_next': has_next
        })
