from django.db.models import Q, Prefetch
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import permissions, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from .models import ChatFolder, ChatFolderRoom, ChatRoom, ChatRoomMember, Message
from .serializers import (
    ChatFolderRoomSerializer, ChatFolderSerializer, ChatRoomCreateSerializer,
    ChatRoomSerializer, MessageCreateSerializer, MessageSerializer,
)


class ChatRoomListView(APIView):
    """채팅방 목록 조회 및 생성"""
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        tags=['Chat'],
        summary='채팅방 목록 조회',
        description='사용자가 참여한 모든 채팅방 목록을 조회합니다.',
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
            Prefetch('messages', queryset=Message.objects.select_related('sender').order_by('-created_at')[:1])
        ).distinct().order_by('-updated_at')
        
        serializer = ChatRoomSerializer(rooms, many=True)
        return Response(serializer.data)
    
    @extend_schema(
        tags=['Chat'],
        summary='채팅방 생성',
        description='새로운 채팅방을 생성합니다. 1:1 채팅 또는 그룹 채팅을 생성할 수 있습니다.',
        request=ChatRoomCreateSerializer,
        responses={
            201: ChatRoomSerializer,
            400: OpenApiResponse(description='잘못된 요청'),
        }
    )
    def post(self, request):
        """채팅방 생성"""
        serializer = ChatRoomCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        room_type = serializer.validated_data['room_type']
        name = serializer.validated_data.get('name')
        description = serializer.validated_data.get('description')
        member_ids = serializer.validated_data.get('member_ids', [])
        user = request.user
        
        # 1:1 채팅인 경우
        if room_type == 'direct':
            if len(member_ids) != 1:
                return Response(
                    {'error': '1:1 채팅은 상대방 1명만 선택해야 합니다.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # 이미 존재하는 1:1 채팅방이 있는지 확인
            other_user_id = member_ids[0]
            if other_user_id == user.id:
                return Response(
                    {'error': '자기 자신과는 1:1 채팅을 생성할 수 없습니다.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            try:
                other_user = User.objects.get(id=other_user_id)
            except User.DoesNotExist:
                return Response(
                    {'error': '존재하지 않는 사용자입니다.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # 기존 1:1 채팅방 확인
            existing_room = ChatRoom.objects.filter(
                room_type='direct',
                members__user=user
            ).filter(
                members__user=other_user
            ).distinct().first()
            
            if existing_room:
                serializer = ChatRoomSerializer(existing_room)
                return Response(serializer.data, status=status.HTTP_200_OK)
            
            # 새 1:1 채팅방 생성
            room = ChatRoom.objects.create(
                room_type='direct',
                created_by=user
            )
            
            # 멤버 추가
            ChatRoomMember.objects.create(room=room, user=user, role='member')
            ChatRoomMember.objects.create(room=room, user=other_user, role='member')
        
        # 그룹 채팅인 경우
        else:
            if not name:
                return Response(
                    {'error': '그룹 채팅방 이름은 필수입니다.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # 그룹 채팅방 생성
            room = ChatRoom.objects.create(
                room_type='group',
                name=name,
                description=description,
                created_by=user
            )
            
            # 생성자를 방장으로 추가
            ChatRoomMember.objects.create(room=room, user=user, role='owner')
            
            # 다른 멤버들 추가
            for member_id in member_ids:
                if member_id != user.id:
                    try:
                        member_user = User.objects.get(id=member_id)
                        ChatRoomMember.objects.get_or_create(
                            room=room,
                            user=member_user,
                            defaults={'role': 'member'}
                        )
                    except User.DoesNotExist:
                        continue
        
        serializer = ChatRoomSerializer(room)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class ChatRoomDetailView(APIView):
    """채팅방 상세 조회 및 수정"""
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        tags=['Chat'],
        summary='채팅방 상세 조회',
        description='채팅방의 상세 정보를 조회합니다.',
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
        
        serializer = ChatRoomSerializer(room)
        return Response(serializer.data)
    
    @extend_schema(
        tags=['Chat'],
        summary='채팅방 정보 수정',
        description='그룹 채팅방의 이름과 설명을 수정합니다.',
        request={
            'type': 'object',
            'properties': {
                'name': {'type': 'string'},
                'description': {'type': 'string'},
            }
        },
        responses={
            200: ChatRoomSerializer,
            403: OpenApiResponse(description='권한 없음'),
            404: OpenApiResponse(description='채팅방을 찾을 수 없음'),
        }
    )
    def patch(self, request, room_id):
        """채팅방 정보 수정"""
        try:
            room = ChatRoom.objects.get(id=room_id)
        except ChatRoom.DoesNotExist:
            return Response(
                {'error': '채팅방을 찾을 수 없습니다.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
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
        
        serializer = ChatRoomSerializer(room)
        return Response(serializer.data)


class MessageListView(APIView):
    """메시지 목록 조회 및 전송"""
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        tags=['Chat'],
        summary='메시지 목록 조회',
        description='채팅방의 메시지 목록을 조회합니다.',
        parameters=[
            {
                'name': 'page',
                'in': 'query',
                'description': '페이지 번호',
                'required': False,
                'schema': {'type': 'integer', 'default': 1}
            },
            {
                'name': 'page_size',
                'in': 'query',
                'description': '페이지당 메시지 수',
                'required': False,
                'schema': {'type': 'integer', 'default': 50}
            },
        ],
        responses={
            200: MessageSerializer(many=True),
            404: OpenApiResponse(description='채팅방을 찾을 수 없음'),
        }
    )
    def get(self, request, room_id):
        """메시지 목록 조회"""
        try:
            room = ChatRoom.objects.get(id=room_id)
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
        
        # 페이지네이션
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 50))
        offset = (page - 1) * page_size
        
        # 메시지 조회 (최신순)
        messages = Message.objects.filter(room=room).select_related(
            'sender', 'reply_to', 'reply_to__sender', 'asset'
        ).order_by('-created_at')[offset:offset + page_size]
        
        serializer = MessageSerializer(list(reversed(messages)), many=True)
        return Response({
            'results': serializer.data,
            'page': page,
            'page_size': page_size,
            'total': Message.objects.filter(room=room).count()
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
        try:
            room = ChatRoom.objects.get(id=room_id)
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


class ChatFolderListView(APIView):
    """채팅방 폴더 목록 조회 및 생성"""
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        tags=['Chat'],
        summary='폴더 목록 조회',
        description='사용자의 채팅방 폴더 목록을 조회합니다.',
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
        request={
            'type': 'object',
            'properties': {
                'name': {'type': 'string'},
                'color': {'type': 'string', 'format': 'color'},
            },
            'required': ['name']
        },
        responses={
            201: ChatFolderSerializer,
            400: OpenApiResponse(description='잘못된 요청'),
        }
    )
    def post(self, request):
        """폴더 생성"""
        name = request.data.get('name')
        color = request.data.get('color', '#000000')
        
        if not name:
            return Response(
                {'error': '폴더 이름은 필수입니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        folder = ChatFolder.objects.create(
            user=request.user,
            name=name,
            color=color
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
        serializer = ChatFolderRoomSerializer(folder_rooms, many=True)
        return Response(serializer.data)
    
    @extend_schema(
        tags=['Chat'],
        summary='폴더 수정',
        description='폴더의 이름과 색상을 수정합니다.',
        request={
            'type': 'object',
            'properties': {
                'name': {'type': 'string'},
                'color': {'type': 'string', 'format': 'color'},
            }
        },
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
        
        if name:
            folder.name = name
        if color:
            folder.color = color
        
        folder.save()
        
        serializer = ChatFolderSerializer(folder)
        return Response(serializer.data)
    
    @extend_schema(
        tags=['Chat'],
        summary='폴더 삭제',
        description='폴더를 삭제합니다. 폴더에 포함된 채팅방은 삭제되지 않습니다.',
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
        request={
            'type': 'object',
            'properties': {
                'room_id': {'type': 'string', 'format': 'uuid'},
            },
            'required': ['room_id']
        },
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
        
        try:
            room = ChatRoom.objects.get(id=room_id)
        except ChatRoom.DoesNotExist:
            return Response(
                {'error': '채팅방을 찾을 수 없습니다.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
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
        
        serializer = ChatFolderRoomSerializer(folder_room)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    @extend_schema(
        tags=['Chat'],
        summary='폴더에서 채팅방 제거',
        description='폴더에서 채팅방을 제거합니다. 채팅방 자체는 삭제되지 않습니다.',
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
