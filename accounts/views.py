from django.contrib.auth import get_user_model
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import permissions, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import RefreshToken, UntypedToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from config.constants import (
    REFRESH_TOKEN_EXPIRES_DAYS,
    VERIFICATION_CODE_EXPIRES_SECONDS,
    VERIFIED_TOKEN_EXPIRES_SECONDS,
)

from .models import UserDevice
from .response_serializers import (
    DevicePrivateKeyResponseSerializer,
    MessageResponseSerializer,
    PhoneVerifyResponseSerializer,
    TokenPairResponseSerializer,
    TokenResponseSerializer,
    UserDevicesPublicResponseSerializer,
    UserPublicKeyResponseSerializer,
    VerificationCodeResponseSerializer,
)
from .serializers import (
    CustomTokenObtainPairSerializer,
    PhoneVerificationSerializer,
    PhoneVerifySerializer,
    UserDeleteSerializer,
    UserDeviceCreateSerializer,
    UserDeviceSerializer,
    UserRegistrationSerializer,
    UserSerializer,
)
from .sms_service import SolapiService
from .utils import PhoneVerificationStorage, RefreshTokenStorage

User = get_user_model()


class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer
    
    @extend_schema(
        tags=['Auth'],
        summary='로그인',
        description='''
        전화번호와 비밀번호로 로그인하고 JWT 토큰을 발급합니다.
        ''',
        request=CustomTokenObtainPairSerializer,
        responses={
            200: TokenPairResponseSerializer,
            400: OpenApiResponse(description='로그인 실패 (전화번호 또는 비밀번호 오류)'),
        }
    )
    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        
        if response.status_code == 200:
            refresh_token = response.data.get('refresh')
            access_token = response.data.get('access')
            
            try:
                decoded_data = UntypedToken(access_token)
                user_id = decoded_data['user_id']
                
                RefreshTokenStorage.save_refresh_token(
                    user_id=user_id,
                    refresh_token=refresh_token,
                    expires_in_days=REFRESH_TOKEN_EXPIRES_DAYS
                )
            except (InvalidToken, TokenError):
                pass
        
        return response


class CustomTokenRefreshView(TokenRefreshView):
    
    @extend_schema(
        tags=['Auth'],
        summary='Token Refresh',
        description='Refresh Token을 사용하여 새로운 Access Token을 발급합니다.',
        responses={
            200: TokenPairResponseSerializer,
            401: OpenApiResponse(description='토큰이 유효하지 않거나 만료됨'),
        }
    )
    def post(self, request, *args, **kwargs):
        refresh_token = request.data.get('refresh')
        
        if not refresh_token:
            return Response(
                {'error': 'Refresh token is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            decoded_data = UntypedToken(refresh_token)
            user_id = decoded_data['user_id']
            
            if not RefreshTokenStorage.is_token_valid(user_id, refresh_token):
                return Response(
                    {'error': 'Invalid or expired refresh token'},
                    status=status.HTTP_401_UNAUTHORIZED
                )
            
            RefreshTokenStorage.delete_refresh_token(user_id, refresh_token)
            
            response = super().post(request, *args, **kwargs)
            
            if response.status_code == 200:
                new_refresh_token = response.data.get('refresh')
                
                RefreshTokenStorage.save_refresh_token(
                    user_id=user_id,
                    refresh_token=new_refresh_token,
                    expires_in_days=REFRESH_TOKEN_EXPIRES_DAYS
                )
            
            return response
            
        except (InvalidToken, TokenError):
            return Response(
                {'error': 'Invalid token'},
                status=status.HTTP_401_UNAUTHORIZED
            )


class RegisterView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    parser_classes = [MultiPartParser, FormParser]
    
    @extend_schema(
        tags=['Auth'],
        summary='회원가입',
        description='''
        새로운 사용자를 등록하고 JWT 토큰을 발급합니다.
        ''',
        request={
            'multipart/form-data': {
                'type': 'object',
                'properties': {
                    'phone_number': {'type': 'string', 'description': '전화번호 (예: 01012345678)'},
                    'name': {'type': 'string', 'description': '이름'},
                    'password': {'type': 'string', 'format': 'password', 'description': '비밀번호 (최소 8자)'},
                    'verified_token': {'type': 'string', 'description': '전화번호 인증 완료 토큰'},
                    'profile_image': {'type': 'string', 'format': 'binary', 'description': '프로필 이미지 (선택사항)'},
                    'public_key': {'type': 'string', 'description': 'E2EE 공개키 (PEM 형식, 선택사항)'},
                    'device_name': {'type': 'string', 'description': '기기 이름 (선택사항, 예: iPhone 14)'},
                    'device_fingerprint': {'type': 'string', 'description': '기기 지문 (선택사항, 고유 식별자)'},
                    'encrypted_private_key': {'type': 'string', 'description': '암호화된 개인키 (선택사항, JSON 문자열)'},
                },
                'required': ['phone_number', 'name', 'password', 'verified_token']
            },
            'application/json': UserRegistrationSerializer,
        },
        responses={
            201: TokenResponseSerializer,
            400: OpenApiResponse(description='잘못된 요청'),
        }
    )
    def post(self, request):
        serializer = UserRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        
        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)
        refresh_token = str(refresh)
        
        RefreshTokenStorage.save_refresh_token(
            user_id=user.id,
            refresh_token=refresh_token,
            expires_in_days=REFRESH_TOKEN_EXPIRES_DAYS
        )
        
        user_serializer = UserSerializer(user)
        
        return Response(
            {
                'user': user_serializer.data,
                'access': access_token,
                'refresh': refresh_token,
            },
            status=status.HTTP_201_CREATED
        )


class LogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = None
    
    @extend_schema(
        tags=['Auth'],
        summary='로그아웃',
        description='Refresh Token을 삭제하여 로그아웃합니다.',
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'refresh': {'type': 'string'}
                }
            }
        },
        responses={
            200: MessageResponseSerializer,
        }
    )
    def post(self, request):
        refresh_token = request.data.get('refresh')
        
        if refresh_token:
            RefreshTokenStorage.delete_refresh_token(
                user_id=request.user.id,
                refresh_token=refresh_token
            )
        
        return Response(
            {'message': 'Successfully logged out'},
            status=status.HTTP_200_OK
        )


class UserMeView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = UserSerializer
    
    @extend_schema(
        tags=['User'],
        summary='내 정보 조회',
        description='로그인한 사용자의 정보를 조회합니다.',
        responses={
            200: UserSerializer,
        }
    )
    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)


class UserPublicKeyView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        tags=['User'],
        summary='사용자 공개키 조회',
        description='특정 사용자의 공개키를 조회합니다. (1:1 채팅 생성 시 필요)',
        responses={
            200: UserPublicKeyResponseSerializer,
            404: OpenApiResponse(description='사용자를 찾을 수 없음'),
        }
    )
    def get(self, request, user_id):
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response(
                {'error': '사용자를 찾을 수 없습니다.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        return Response({
            'user_id': str(user.id),
            'name': user.name,
            'public_key': user.public_key
        }, status=status.HTTP_200_OK)


class SendVerificationCodeView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    serializer_class = PhoneVerificationSerializer
    
    @extend_schema(
        tags=['Auth'],
        summary='인증번호 전송',
        description='전화번호로 인증번호를 SMS로 전송합니다.',
        request=PhoneVerificationSerializer,
        responses={
            200: VerificationCodeResponseSerializer,
            400: OpenApiResponse(description='잘못된 요청'),
            429: OpenApiResponse(description='요청 제한 초과'),
            500: OpenApiResponse(description='SMS 발송 실패'),
        }
    )
    def post(self, request):
        serializer = PhoneVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        phone_number = serializer.validated_data['phone_number']
        
        from utils.encryption import EncryptionService

        for user in User.objects.all():
            if EncryptionService.check_phone_number(phone_number, user.phone_number):
                return Response(
                    {'error': '이미 가입된 전화번호입니다.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        from django.conf import settings
        limit_seconds = 3 if settings.DEBUG else 60
        
        if not PhoneVerificationStorage.check_rate_limit(phone_number, limit_seconds=limit_seconds):
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Rate limit check failed for {phone_number}. This might be a Redis connection issue.")
            
            error_message = '요청이 너무 빈번합니다. 3초 후 다시 시도해주세요.' if settings.DEBUG else '요청이 너무 빈번합니다. 1분 후 다시 시도해주세요.'
            
            return Response(
                {'error': error_message},
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )
        
        sms_service = SolapiService()
        verification_code = sms_service.generate_verification_code()
        
        result = sms_service.send_verification_code(phone_number, verification_code)
        
        if not result['success']:
            return Response(
                {'error': f'SMS 발송 실패: {result.get("error", "Unknown error")}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        PhoneVerificationStorage.save_verification_code(phone_number, verification_code, expires_in_seconds=VERIFICATION_CODE_EXPIRES_SECONDS)
        
        PhoneVerificationStorage.reset_attempts(phone_number)
        
        return Response(
            {'message': '인증번호가 전송되었습니다.'},
            status=status.HTTP_200_OK
        )


class VerifyPhoneView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    serializer_class = PhoneVerifySerializer
    
    @extend_schema(
        tags=['Auth'],
        summary='인증번호 검증',
        description='인증번호를 검증하고 인증 완료 토큰을 발급합니다.',
        request=PhoneVerifySerializer,
        responses={
            200: PhoneVerifyResponseSerializer,
            400: OpenApiResponse(description='인증번호 불일치 또는 만료'),
            429: OpenApiResponse(description='시도 횟수 초과'),
        }
    )
    def post(self, request):
        serializer = PhoneVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        phone_number = serializer.validated_data['phone_number']
        code = serializer.validated_data['code']
        
        attempts = PhoneVerificationStorage.get_attempts(phone_number)
        if attempts >= 5:
            return Response(
                {'error': '인증 시도 횟수를 초과했습니다. 1시간 후 다시 시도해주세요.'},
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )
        
        stored_code = PhoneVerificationStorage.get_verification_code(phone_number)
        
        if not stored_code:
            PhoneVerificationStorage.increment_attempts(phone_number)
            return Response(
                {'error': '인증번호가 만료되었거나 존재하지 않습니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if stored_code != code:
            PhoneVerificationStorage.increment_attempts(phone_number)
            remaining_attempts = 5 - PhoneVerificationStorage.get_attempts(phone_number)
            return Response(
                {'error': f'인증번호가 일치하지 않습니다. 남은 시도 횟수: {remaining_attempts}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        PhoneVerificationStorage.delete_verification_code(phone_number)
        
        import uuid
        verified_token = str(uuid.uuid4())
        PhoneVerificationStorage.save_verified_token(phone_number, verified_token, expires_in_seconds=VERIFIED_TOKEN_EXPIRES_SECONDS)
        
        PhoneVerificationStorage.reset_attempts(phone_number)
        
        return Response(
            {
                'message': '인증이 완료되었습니다.',
                'verified_token': verified_token,
                'expires_in': VERIFIED_TOKEN_EXPIRES_SECONDS
            },
            status=status.HTTP_200_OK
        )


class DeviceListView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        tags=['Device'],
        summary='내 기기 목록 조회',
        description='현재 사용자의 등록된 모든 기기 목록을 조회합니다.',
        responses={
            200: UserDeviceSerializer(many=True),
        }
    )
    def get(self, request):
        """내 기기 목록 조회"""
        devices = UserDevice.objects.filter(user=request.user).order_by('-last_active')
        serializer = UserDeviceSerializer(devices, many=True)
        return Response(serializer.data)
    
    @extend_schema(
        tags=['Device'],
        summary='새 기기 등록',
        description='새로운 기기를 등록합니다. 기기 지문과 암호화된 개인키를 저장합니다.',
        request=UserDeviceCreateSerializer,
        responses={
            201: OpenApiResponse(
                description='기기 등록 성공',
                response=UserDeviceSerializer
            ),
            400: OpenApiResponse(description='잘못된 요청 (중복된 기기 등록 등)'),
        }
    )
    def post(self, request):
        """새 기기 등록"""
        serializer = UserDeviceCreateSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        device = serializer.save()
        
        result_serializer = UserDeviceSerializer(device)
        return Response(result_serializer.data, status=status.HTTP_201_CREATED)


class DevicePrivateKeyView(APIView):
    """기기의 암호화된 개인키 조회 (키 동기화용)"""
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        tags=['Device'],
        summary='기기의 암호화된 개인키 가져오기',
        description='새 기기에서 로그인 시 기존 기기의 암호화된 개인키를 가져옵니다.',
        responses={
            200: DevicePrivateKeyResponseSerializer,
            403: OpenApiResponse(description='보안상 접근 불가 (비활성 기기)'),
            404: OpenApiResponse(description='기기를 찾을 수 없음'),
        }
    )
    def get(self, request, device_id):
        """기기의 암호화된 개인키 가져오기"""
        from datetime import timedelta

        from django.utils import timezone
        
        try:
            device = UserDevice.objects.get(id=device_id, user=request.user)
        except UserDevice.DoesNotExist:
            return Response(
                {'error': '기기를 찾을 수 없습니다.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        if not device.is_primary:
            time_threshold = timezone.now() - timedelta(hours=24)
            if device.last_active < time_threshold:
                return Response(
                    {'error': '보안상 최근에 활성화된 기기의 키만 가져올 수 있습니다. 해당 기기에서 다시 로그인해주세요.'},
                    status=status.HTTP_403_FORBIDDEN
                )
        
        return Response({
            'device_id': str(device.id),
            'device_name': device.device_name,
            'encrypted_private_key': device.encrypted_private_key
        })


class UserDevicesPublicView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        tags=['Device'],
        summary='사용자의 기기 목록 조회 (공개 정보만)',
        description='다른 사용자의 기기 목록을 조회합니다. 개인키 정보는 포함되지 않습니다.',
        responses={
            200: UserDevicesPublicResponseSerializer,
            404: OpenApiResponse(description='사용자를 찾을 수 없음'),
        }
    )
    def get(self, request, user_id):
        """사용자의 기기 목록 조회 (공개 정보만)"""
        try:
            target_user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response(
                {'error': '사용자를 찾을 수 없습니다.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        devices = UserDevice.objects.filter(user=target_user).order_by('-is_primary', '-last_active')
        
        return Response({
            'user_id': str(target_user.id),
            'name': target_user.name,
            'device_count': devices.count(),
            'devices': [
                {
                    'id': str(device.id),
                    'device_name': device.device_name,
                    'is_primary': device.is_primary,
                }
                for device in devices
            ]
        })


class UserDeleteView(APIView):
    """회원 탈퇴"""
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        tags=['User'],
        summary='회원 탈퇴',
        description='회원 탈퇴를 진행합니다.',
        request=UserDeleteSerializer,
        responses={
            200: MessageResponseSerializer,
            400: OpenApiResponse(description='잘못된 요청 (비밀번호 불일치 등)'),
        }
    )
    def delete(self, request):
        """회원 탈퇴 처리"""
        serializer = UserDeleteSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        
        user = request.user
        user_id = user.id
        
        RefreshTokenStorage.delete_all_user_tokens(user_id)
        
        user.delete()
        
        return Response(
            {
                'message': '회원 탈퇴가 완료되었습니다. 그동안 이용해주셔서 감사합니다.'
            },
            status=status.HTTP_200_OK
        )

