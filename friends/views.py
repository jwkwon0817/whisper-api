from django.db.models import Q
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from utils.encryption import EncryptionService

from .models import Friend
from .response_serializers import MessageResponseSerializer
from .serializers import (
    FriendRequestSerializer,
    FriendResponseSerializer,
    FriendListItemSerializer,
    FriendSerializer,
)


class FriendRequestView(APIView):
    """친구 요청 보내기"""
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        tags=['Friends'],
        summary='친구 요청 보내기',
        description='전화번호로 친구 요청을 보냅니다.',
        request=FriendRequestSerializer,
        responses={
            201: FriendSerializer,
            400: OpenApiResponse(description='잘못된 요청'),
            404: OpenApiResponse(description='사용자를 찾을 수 없음'),
        }
    )
    def post(self, request):
        """친구 요청 보내기"""
        serializer = FriendRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        phone_number = serializer.validated_data['phone_number']
        user = request.user
        
        # 전화번호로 사용자 찾기
        receiver = None
        for u in User.objects.all():
            if EncryptionService.check_phone_number(phone_number, u.phone_number):
                receiver = u
                break
        
        if not receiver:
            return Response(
                {'error': '해당 전화번호로 가입된 사용자를 찾을 수 없습니다.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # 자기 자신에게 요청 불가
        if receiver == user:
            return Response(
                {'error': '자기 자신에게 친구 요청을 보낼 수 없습니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 이미 친구 요청이 있는지 확인
        existing_request = Friend.objects.filter(
            Q(requester=user, receiver=receiver) | Q(requester=receiver, receiver=user)
        ).first()
        
        if existing_request:
            if existing_request.status == 'pending':
                return Response(
                    {'error': '이미 친구 요청이 대기 중입니다.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            elif existing_request.status == 'accepted':
                return Response(
                    {'error': '이미 친구입니다.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            else:
                # 거절된 경우 새로 요청 가능
                existing_request.status = 'pending'
                existing_request.requester = user
                existing_request.receiver = receiver
                existing_request.save()
                serializer = FriendSerializer(existing_request)
                return Response(serializer.data, status=status.HTTP_201_CREATED)
        
        # 새 친구 요청 생성
        friend_request = Friend.objects.create(
            requester=user,
            receiver=receiver,
            status='pending'
        )
        
        serializer = FriendSerializer(friend_request)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class FriendListView(APIView):
    """친구 목록 조회"""
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        tags=['Friends'],
        summary='친구 목록 조회',
        description='수락된 친구 목록을 조회합니다.',
        responses={
            200: FriendListItemSerializer(many=True),
        }
    )
    def get(self, request):
        """친구 목록 조회"""
        user = request.user
        
        # 수락된 친구 관계만 조회
        friends = Friend.objects.filter(
            Q(requester=user) | Q(receiver=user),
            status='accepted'
        ).select_related('requester', 'receiver').order_by('-updated_at')
        
        # 상대방 정보만 추출
        friend_list = []
        for friend in friends:
            # 현재 사용자가 아닌 상대방 정보만 추가
            other_user = friend.receiver if friend.requester == user else friend.requester
            friend_list.append({
                'id': friend.id,  # 친구 관계 ID (삭제 시 사용)
                'user': {
                    'id': str(other_user.id),
                    'name': other_user.name,
                    'profile_image': other_user.profile_image,
                }
            })
        
        serializer = FriendListItemSerializer(friend_list, many=True)
        return Response(serializer.data)


class FriendRequestListView(APIView):
    """받은 친구 요청 목록 조회"""
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        tags=['Friends'],
        summary='받은 친구 요청 목록 조회',
        description='내가 받은 친구 요청 목록을 조회합니다.',
        responses={
            200: FriendListItemSerializer(many=True),
        }
    )
    def get(self, request):
        """받은 친구 요청 목록 조회"""
        user = request.user
        
        # 받은 요청 중 대기 중인 것만 조회
        requests = Friend.objects.filter(
            receiver=user,
            status='pending'
        ).select_related('requester', 'receiver').order_by('-created_at')
        
        # 요청자 정보만 추출 (receiver는 항상 현재 사용자)
        request_list = []
        for friend_request in requests:
            request_list.append({
                'id': friend_request.id,  # 친구 관계 ID (응답 시 사용)
                'user': {
                    'id': str(friend_request.requester.id),
                    'name': friend_request.requester.name,
                    'profile_image': friend_request.requester.profile_image,
                }
            })
        
        serializer = FriendListItemSerializer(request_list, many=True)
        return Response(serializer.data)


class FriendResponseView(APIView):
    """친구 요청 수락/거절"""
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        tags=['Friends'],
        summary='친구 요청 수락/거절',
        description='받은 친구 요청을 수락하거나 거절합니다.',
        request=FriendResponseSerializer,
        responses={
            200: FriendSerializer,
            404: OpenApiResponse(description='친구 요청을 찾을 수 없음'),
        }
    )
    def post(self, request, friend_id):
        """친구 요청 수락/거절"""
        serializer = FriendResponseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        action = serializer.validated_data['action']
        user = request.user
        
        try:
            friend_request = Friend.objects.get(id=friend_id, receiver=user, status='pending')
        except Friend.DoesNotExist:
            return Response(
                {'error': '친구 요청을 찾을 수 없습니다.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        if action == 'accept':
            friend_request.status = 'accepted'
            friend_request.save()
        else:
            friend_request.status = 'rejected'
            friend_request.save()
        
        serializer = FriendSerializer(friend_request)
        return Response(serializer.data)


class FriendDeleteView(APIView):
    """친구 삭제"""
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        tags=['Friends'],
        summary='친구 삭제',
        description='친구 관계를 삭제합니다.',
        responses={
            200: MessageResponseSerializer,
            404: OpenApiResponse(description='친구 관계를 찾을 수 없음'),
        }
    )
    def delete(self, request, friend_id):
        """친구 삭제"""
        user = request.user
        
        try:
            friend = Friend.objects.filter(
                Q(requester=user) | Q(receiver=user),
                status='accepted'
            ).get(id=friend_id)
        except Friend.DoesNotExist:
            return Response(
                {'error': '친구 관계를 찾을 수 없습니다.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        friend.delete()
        return Response({'message': '친구가 삭제되었습니다.'}, status=status.HTTP_200_OK)
