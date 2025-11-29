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
    FriendListItemSerializer,
    FriendRequestSerializer,
    FriendResponseSerializer,
    FriendSerializer,
)


class FriendRequestView(APIView):
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
        serializer = FriendRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        phone_number = serializer.validated_data['phone_number']
        user = request.user
        
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
        
        if receiver == user:
            return Response(
                {'error': '자기 자신에게 친구 요청을 보낼 수 없습니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
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
                existing_request.status = 'pending'
                existing_request.requester = user
                existing_request.receiver = receiver
                existing_request.save()
                serializer = FriendSerializer(existing_request)
                return Response(serializer.data, status=status.HTTP_201_CREATED)
        
        friend_request = Friend.objects.create(
            requester=user,
            receiver=receiver,
            status='pending'
        )
        
        serializer = FriendSerializer(friend_request)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class FriendListView(APIView):
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
        user = request.user
        
        friends = Friend.objects.filter(
            Q(requester=user) | Q(receiver=user),
            status='accepted'
        ).select_related('requester', 'receiver').order_by('-updated_at')
        
        friend_list = []
        for friend in friends:
            other_user = friend.receiver if friend.requester == user else friend.requester
            friend_list.append({
                'id': friend.id,
                'user': {
                    'id': str(other_user.id),
                    'name': other_user.name,
                    'profile_image': other_user.profile_image,
                }
            })
        
        serializer = FriendListItemSerializer(friend_list, many=True)
        return Response(serializer.data)


class FriendRequestListView(APIView):
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
        user = request.user
        
        requests = Friend.objects.filter(
            receiver=user,
            status='pending'
        ).select_related('requester', 'receiver').order_by('-created_at')
        
        request_list = []
        for friend_request in requests:
            request_list.append({
                'id': friend_request.id,
                'user': {
                    'id': str(friend_request.requester.id),
                    'name': friend_request.requester.name,
                    'profile_image': friend_request.requester.profile_image,
                }
            })
        
        serializer = FriendListItemSerializer(request_list, many=True)
        return Response(serializer.data)


class FriendResponseView(APIView):
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
