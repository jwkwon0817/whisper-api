"""
Swagger 응답 전용 시리얼라이저
drf-spectacular에서 API 응답을 명확하게 표시하기 위한 시리얼라이저 모음
"""

from rest_framework import serializers
from .serializers import UserSerializer


class TokenPairResponseSerializer(serializers.Serializer):
    """JWT 토큰 쌍 응답 시리얼라이저 (로그인, 토큰 갱신)"""
    access = serializers.CharField(read_only=True, help_text='Access Token (15분 유효)')
    refresh = serializers.CharField(read_only=True, help_text='Refresh Token (7일 유효)')
    device_registered = serializers.BooleanField(read_only=True, help_text='현재 기기가 등록되어 있는지 여부')
    device_id = serializers.UUIDField(read_only=True, allow_null=True, help_text='등록된 기기 ID (없으면 null)')


class TokenResponseSerializer(serializers.Serializer):
    """JWT 토큰 응답 시리얼라이저 (회원가입)"""
    user = UserSerializer(read_only=True)
    access = serializers.CharField(read_only=True, help_text='Access Token (15분 유효)')
    refresh = serializers.CharField(read_only=True, help_text='Refresh Token (7일 유효)')


class MessageResponseSerializer(serializers.Serializer):
    """단순 메시지 응답 시리얼라이저"""
    message = serializers.CharField(read_only=True)


class VerificationCodeResponseSerializer(serializers.Serializer):
    """인증번호 전송 응답 시리얼라이저"""
    message = serializers.CharField(read_only=True)


class PhoneVerifyResponseSerializer(serializers.Serializer):
    """인증번호 검증 응답 시리얼라이저"""
    message = serializers.CharField(read_only=True)
    verified_token = serializers.CharField(read_only=True, help_text='회원가입 시 사용할 인증 토큰')
    expires_in = serializers.IntegerField(read_only=True, help_text='토큰 만료 시간 (초)')


class PublicKeyResponseSerializer(serializers.Serializer):
    """공개키 등록 응답 시리얼라이저"""
    message = serializers.CharField(read_only=True)
    public_key = serializers.CharField(read_only=True)


class UserPublicKeyResponseSerializer(serializers.Serializer):
    """사용자 공개키 조회 응답 시리얼라이저"""
    user_id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    public_key = serializers.CharField(read_only=True, allow_null=True)


class UserSearchItemSerializer(serializers.Serializer):
    """사용자 검색 결과 아이템"""
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    profile_image = serializers.URLField(read_only=True, allow_null=True)
    has_public_key = serializers.BooleanField(read_only=True)


class UserSearchResponseSerializer(serializers.Serializer):
    """사용자 검색 응답 시리얼라이저"""
    results = UserSearchItemSerializer(many=True, read_only=True)
    count = serializers.IntegerField(read_only=True)


class DevicePublicItemSerializer(serializers.Serializer):
    """기기 공개 정보 아이템"""
    id = serializers.UUIDField(read_only=True)
    device_name = serializers.CharField(read_only=True)
    is_primary = serializers.BooleanField(read_only=True)


class UserDevicesPublicResponseSerializer(serializers.Serializer):
    """사용자 기기 목록 공개 응답"""
    user_id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    device_count = serializers.IntegerField(read_only=True)
    devices = DevicePublicItemSerializer(many=True, read_only=True)


class DevicePrivateKeyResponseSerializer(serializers.Serializer):
    """기기 개인키 조회 응답"""
    device_id = serializers.UUIDField(read_only=True)
    device_name = serializers.CharField(read_only=True)
    encrypted_private_key = serializers.CharField(read_only=True)

