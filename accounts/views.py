from django.contrib.auth import get_user_model
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import permissions, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import RefreshToken, UntypedToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .models import UserDevice
from .response_serializers import (
    DevicePrivateKeyResponseSerializer,
    MessageResponseSerializer,
    PhoneVerifyResponseSerializer,
    PublicKeyResponseSerializer,
    TokenPairResponseSerializer,
    TokenResponseSerializer,
    UserDevicesPublicResponseSerializer,
    UserPublicKeyResponseSerializer,
    UserSearchResponseSerializer,
    VerificationCodeResponseSerializer,
)
from .serializers import (
    CustomTokenObtainPairSerializer,
    DevUserRegistrationSerializer,
    PasswordChangeSerializer,
    PhoneVerificationSerializer,
    PhoneVerifySerializer,
    PublicKeySerializer,
    UserDeleteSerializer,
    UserDeviceCreateSerializer,
    UserDevicePrivateKeySerializer,
    UserDeviceSerializer,
    UserRegistrationSerializer,
    UserSerializer,
    UserUpdateSerializer,
)
from .sms_service import SolapiService
from .utils import PhoneVerificationStorage, RefreshTokenStorage

User = get_user_model()


class CustomTokenObtainPairView(TokenObtainPairView):
    """로그인 시 Refresh Token을 Redis에 저장"""
    serializer_class = CustomTokenObtainPairSerializer
    
    @extend_schema(
        tags=['Auth'],
        summary='로그인',
        description='''
        전화번호와 비밀번호로 로그인하고 JWT 토큰을 발급합니다.
        
        선택 항목:
        - device_fingerprint: 기기 지문 (제공 시 기존 기기 확인 및 last_active 업데이트)
        
        응답:
        - device_registered: 현재 기기가 등록되어 있는지 여부
        - device_id: 등록된 기기 ID (없으면 null)
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
                # Access Token에서 user_id 추출
                decoded_data = UntypedToken(access_token)
                user_id = decoded_data['user_id']
                
                # Refresh Token을 Redis에 저장
                RefreshTokenStorage.save_refresh_token(
                    user_id=user_id,
                    refresh_token=refresh_token,
                    expires_in_days=7
                )
            except (InvalidToken, TokenError) as e:
                pass  # 에러 처리
        
        return response


class CustomTokenRefreshView(TokenRefreshView):
    """Refresh Token 갱신 시 Redis에서 검증"""
    
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
            # Refresh Token에서 user_id 추출
            decoded_data = UntypedToken(refresh_token)
            user_id = decoded_data['user_id']
            
            # Redis에서 토큰 검증
            if not RefreshTokenStorage.is_token_valid(user_id, refresh_token):
                return Response(
                    {'error': 'Invalid or expired refresh token'},
                    status=status.HTTP_401_UNAUTHORIZED
                )
            
            # 기존 토큰 삭제
            RefreshTokenStorage.delete_refresh_token(user_id, refresh_token)
            
            # 새 토큰 발급
            response = super().post(request, *args, **kwargs)
            
            if response.status_code == 200:
                new_refresh_token = response.data.get('refresh')
                
                # 새 Refresh Token을 Redis에 저장
                RefreshTokenStorage.save_refresh_token(
                    user_id=user_id,
                    refresh_token=new_refresh_token,
                    expires_in_days=7
                )
            
            return response
            
        except (InvalidToken, TokenError) as e:
            return Response(
                {'error': 'Invalid token'},
                status=status.HTTP_401_UNAUTHORIZED
            )


class RegisterView(APIView):
    """회원가입 뷰"""
    permission_classes = [permissions.AllowAny]
    authentication_classes = []  # 인증 불필요
    parser_classes = [MultiPartParser, FormParser]  # 파일 업로드 지원
    
    @extend_schema(
        tags=['Auth'],
        summary='회원가입',
        description='''
        새로운 사용자를 등록하고 JWT 토큰을 발급합니다.
        
        필수 항목:
        - phone_number: 전화번호 (인증 완료된 번호)
        - name: 이름
        - password: 비밀번호 (최소 8자)
        - verified_token: 전화번호 인증 완료 토큰
        
        선택 항목 (E2EE + 멀티 디바이스):
        - public_key: E2EE 공개키 (PEM 형식)
        - device_name: 기기 이름 (예: iPhone 14, Chrome on Mac)
        - device_fingerprint: 기기 고유 식별자
        - encrypted_private_key: 비밀번호로 암호화된 개인키 (JSON 문자열)
        
        ⚠️ 기기 정보는 3개 모두 제공하거나 모두 제공하지 않아야 합니다.
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
        """회원가입 - 사용자 생성 후 JWT 토큰 발급"""
        serializer = UserRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        
        # JWT 토큰 생성
        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)
        refresh_token = str(refresh)
        
        # Refresh Token을 Redis에 저장
        RefreshTokenStorage.save_refresh_token(
            user_id=user.id,
            refresh_token=refresh_token,
            expires_in_days=7
        )
        
        # 사용자 정보 시리얼라이저로 응답
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
    """로그아웃 뷰"""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = None  # Request body 없음
    
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
        """로그아웃 - Refresh Token 삭제"""
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


class UserProfileView(APIView):
    """사용자 프로필 관리 뷰"""
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]  # 파일 업로드 지원
    serializer_class = UserUpdateSerializer
    
    @extend_schema(
        tags=['User'],
        summary='정보 변경',
        description='프로필 사진과 이름을 변경합니다.',
        request=UserUpdateSerializer,
        responses={
            200: UserSerializer,
        }
    )
    def patch(self, request):
        """사용자 정보 수정"""
        serializer = UserUpdateSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class UserMeView(APIView):
    """내 정보 조회 뷰"""
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
        """현재 사용자 정보 조회"""
        serializer = UserSerializer(request.user)
        return Response(serializer.data)


class PasswordChangeView(APIView):
    """비밀번호 변경 뷰"""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = PasswordChangeSerializer
    
    @extend_schema(
        tags=['User'],
        summary='비밀번호 변경',
        description='사용자의 비밀번호를 변경합니다. 변경 후 모든 기기에서 로그아웃됩니다.',
        request=PasswordChangeSerializer,
        responses={
            200: MessageResponseSerializer,
            400: OpenApiResponse(description='잘못된 요청'),
        }
    )
    def patch(self, request):
        """비밀번호 변경"""
        serializer = PasswordChangeSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        
        user = request.user
        user.set_password(serializer.validated_data['new_password'])
        user.save()
        
        # 모든 Refresh Token 삭제 (보안상 강제 로그아웃)
        RefreshTokenStorage.delete_all_user_tokens(user.id)
        
        return Response({'message': '비밀번호가 변경되었습니다.'}, status=status.HTTP_200_OK)


class PublicKeyView(APIView):
    """공개키 등록/수정 뷰"""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = PublicKeySerializer
    
    @extend_schema(
        tags=['User'],
        summary='공개키 등록/수정',
        description='E2EE 공개키를 등록하거나 수정합니다.',
        request=PublicKeySerializer,
        responses={
            200: PublicKeyResponseSerializer,
            400: OpenApiResponse(description='잘못된 요청'),
        }
    )
    def post(self, request):
        """공개키 등록/수정"""
        serializer = PublicKeySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        public_key = serializer.validated_data['public_key']
        request.user.public_key = public_key
        request.user.save(update_fields=['public_key'])
        
        return Response({
            'message': '공개키가 등록되었습니다.',
            'public_key': public_key
        }, status=status.HTTP_200_OK)


class UserPublicKeyView(APIView):
    """사용자 공개키 조회 뷰"""
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
        """사용자 공개키 조회"""
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


class UserSearchView(APIView):
    """사용자 검색 뷰"""
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        tags=['User'],
        summary='사용자 검색',
        description='이름으로 사용자를 검색합니다. (1:1 채팅 생성 시 사용)',
        parameters=[
            OpenApiParameter(
                name='q',
                type=str,
                location=OpenApiParameter.QUERY,
                description='검색어 (이름)',
                required=True
            ),
            OpenApiParameter(
                name='limit',
                type=int,
                location=OpenApiParameter.QUERY,
                description='결과 개수 제한',
                required=False,
                default=20
            ),
        ],
        responses={
            200: UserSearchResponseSerializer,
        }
    )
    def get(self, request):
        """사용자 검색"""
        query = request.query_params.get('q', '').strip()
        limit = int(request.query_params.get('limit', 20))
        
        if not query:
            return Response(
                {'error': '검색어를 입력해주세요.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if len(query) < 2:
            return Response(
                {'error': '검색어는 최소 2자 이상이어야 합니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 이름으로 검색 (본인 제외)
        users = User.objects.filter(
            name__icontains=query
        ).exclude(id=request.user.id)[:limit]
        
        results = []
        for user in users:
            results.append({
                'id': str(user.id),
                'name': user.name,
                'profile_image': user.profile_image,
                'has_public_key': bool(user.public_key)
            })
        
        return Response({
            'results': results,
            'count': len(results)
        }, status=status.HTTP_200_OK)


class SendVerificationCodeView(APIView):
    """인증번호 전송 뷰"""
    permission_classes = [permissions.AllowAny]
    authentication_classes = []  # 인증 불필요
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
        """인증번호 전송"""
        serializer = PhoneVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        phone_number = serializer.validated_data['phone_number']
        
        # 이미 가입된 번호인지 확인 (암호화된 값 복호화 후 비교)
        from utils.encryption import EncryptionService

        # 모든 사용자를 가져와서 복호화 후 비교
        for user in User.objects.all():
            if EncryptionService.check_phone_number(phone_number, user.phone_number):
                return Response(
                    {'error': '이미 가입된 전화번호입니다.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        from django.conf import settings
        limit_seconds = 3 if settings.DEBUG else 60
        
        if not PhoneVerificationStorage.check_rate_limit(phone_number, limit_seconds=limit_seconds):
            # Rate Limit 체크 실패 시 Redis 연결 문제일 수 있으므로 로그 확인
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Rate limit check failed for {phone_number}. This might be a Redis connection issue.")
            
            error_message = '요청이 너무 빈번합니다. 3초 후 다시 시도해주세요.' if settings.DEBUG else '요청이 너무 빈번합니다. 1분 후 다시 시도해주세요.'
            
            return Response(
                {'error': error_message},
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )
        
        # 인증번호 생성
        sms_service = SolapiService()
        verification_code = sms_service.generate_verification_code()
        
        # SMS 발송
        result = sms_service.send_verification_code(phone_number, verification_code)
        
        if not result['success']:
            return Response(
                {'error': f'SMS 발송 실패: {result.get("error", "Unknown error")}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        # 인증번호를 Redis에 저장 (5분 만료)
        PhoneVerificationStorage.save_verification_code(phone_number, verification_code, expires_in_seconds=300)
        
        # 시도 횟수 초기화
        PhoneVerificationStorage.reset_attempts(phone_number)
        
        return Response(
            {'message': '인증번호가 전송되었습니다.'},
            status=status.HTTP_200_OK
        )


class VerifyPhoneView(APIView):
    """인증번호 검증 뷰"""
    permission_classes = [permissions.AllowAny]
    authentication_classes = []  # 인증 불필요
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
        """인증번호 검증"""
        serializer = PhoneVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        phone_number = serializer.validated_data['phone_number']
        code = serializer.validated_data['code']
        
        # 시도 횟수 확인 (최대 5회)
        attempts = PhoneVerificationStorage.get_attempts(phone_number)
        if attempts >= 5:
            return Response(
                {'error': '인증 시도 횟수를 초과했습니다. 1시간 후 다시 시도해주세요.'},
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )
        
        # 인증번호 조회
        stored_code = PhoneVerificationStorage.get_verification_code(phone_number)
        
        if not stored_code:
            PhoneVerificationStorage.increment_attempts(phone_number)
            return Response(
                {'error': '인증번호가 만료되었거나 존재하지 않습니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 인증번호 일치 확인
        if stored_code != code:
            PhoneVerificationStorage.increment_attempts(phone_number)
            remaining_attempts = 5 - PhoneVerificationStorage.get_attempts(phone_number)
            return Response(
                {'error': f'인증번호가 일치하지 않습니다. 남은 시도 횟수: {remaining_attempts}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 인증 성공
        # 인증번호 삭제
        PhoneVerificationStorage.delete_verification_code(phone_number)
        
        # 인증 완료 토큰 생성 및 저장 (10분 만료)
        import uuid
        verified_token = str(uuid.uuid4())
        PhoneVerificationStorage.save_verified_token(phone_number, verified_token, expires_in_seconds=600)
        
        # 시도 횟수 초기화
        PhoneVerificationStorage.reset_attempts(phone_number)
        
        return Response(
            {
                'message': '인증이 완료되었습니다.',
                'verified_token': verified_token,
                'expires_in': 600  # 10분
            },
            status=status.HTTP_200_OK
        )


class DevRegisterView(APIView):
    """개발 모드용 회원가입 뷰 (전화번호 인증 없이)"""
    permission_classes = [permissions.AllowAny]
    authentication_classes = []  # 인증 불필요
    parser_classes = [MultiPartParser, FormParser]  # 파일 업로드 지원
    
    @extend_schema(
        tags=['Auth'],
        summary='[개발 모드] 회원가입 (인증 없이)',
        description='''
        개발 모드에서 전화번호 인증 없이 회원가입합니다. DEBUG=True일 때만 사용 가능합니다.
        
        필수 항목:
        - phone_number: 전화번호
        - name: 이름
        - password: 비밀번호 (최소 8자)
        
        선택 항목 (E2EE + 멀티 디바이스):
        - public_key: E2EE 공개키 (PEM 형식)
        - device_name: 기기 이름 (예: iPhone 14, Chrome on Mac)
        - device_fingerprint: 기기 고유 식별자
        - encrypted_private_key: 비밀번호로 암호화된 개인키 (JSON 문자열)
        
        ⚠️ 기기 정보는 3개 모두 제공하거나 모두 제공하지 않아야 합니다.
        ''',
        request={
            'multipart/form-data': {
                'type': 'object',
                'properties': {
                    'phone_number': {'type': 'string', 'description': '전화번호 (예: 01012345678)'},
                    'name': {'type': 'string', 'description': '이름'},
                    'password': {'type': 'string', 'format': 'password', 'description': '비밀번호 (최소 8자)'},
                    'profile_image': {'type': 'string', 'format': 'binary', 'description': '프로필 이미지 (선택사항)'},
                    'public_key': {'type': 'string', 'description': 'E2EE 공개키 (PEM 형식, 선택사항)'},
                    'device_name': {'type': 'string', 'description': '기기 이름 (선택사항, 예: iPhone 14)'},
                    'device_fingerprint': {'type': 'string', 'description': '기기 지문 (선택사항)'},
                    'encrypted_private_key': {'type': 'string', 'description': '암호화된 개인키 (선택사항, JSON)'},
                },
                'required': ['phone_number', 'name', 'password']
            },
            'application/json': DevUserRegistrationSerializer,
        },
        responses={
            201: TokenResponseSerializer,
            400: OpenApiResponse(description='잘못된 요청'),
            403: OpenApiResponse(description='개발 모드가 아닙니다'),
        }
    )
    def post(self, request):
        """개발 모드용 회원가입 - 전화번호 인증 없이 사용자 생성 후 JWT 토큰 발급"""
        from django.conf import settings

        # 개발 모드가 아니면 접근 불가
        if not settings.DEBUG:
            return Response(
                {'error': '이 API는 개발 모드에서만 사용할 수 있습니다.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = DevUserRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        
        # JWT 토큰 생성
        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)
        refresh_token = str(refresh)
        
        # Refresh Token을 Redis에 저장
        RefreshTokenStorage.save_refresh_token(
            user_id=user.id,
            refresh_token=refresh_token,
            expires_in_days=7
        )
        
        # 사용자 정보 시리얼라이저로 응답
        user_serializer = UserSerializer(user)
        
        return Response(
            {
                'user': user_serializer.data,
                'access': access_token,
                'refresh': refresh_token,
            },
            status=status.HTTP_201_CREATED
        )


class DeviceListView(APIView):
    """기기 목록 조회 및 등록"""
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


class DeviceDetailView(APIView):
    """기기 상세 조회 및 삭제"""
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        tags=['Device'],
        summary='기기 상세 조회',
        description='특정 기기의 상세 정보를 조회합니다.',
        responses={
            200: UserDeviceSerializer,
            404: OpenApiResponse(description='기기를 찾을 수 없음'),
        }
    )
    def get(self, request, device_id):
        """기기 상세 조회"""
        try:
            device = UserDevice.objects.get(id=device_id, user=request.user)
        except UserDevice.DoesNotExist:
            return Response(
                {'error': '기기를 찾을 수 없습니다.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = UserDeviceSerializer(device)
        return Response(serializer.data)
    
    @extend_schema(
        tags=['Device'],
        summary='기기 삭제',
        description='기기를 목록에서 제거합니다. 해당 기기는 더 이상 메시지를 복호화할 수 없게 됩니다.',
        responses={
            204: OpenApiResponse(description='삭제 성공'),
            404: OpenApiResponse(description='기기를 찾을 수 없음'),
        }
    )
    def delete(self, request, device_id):
        """기기 삭제"""
        try:
            device = UserDevice.objects.get(id=device_id, user=request.user)
        except UserDevice.DoesNotExist:
            return Response(
                {'error': '기기를 찾을 수 없습니다.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        device.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class DevicePrivateKeyView(APIView):
    """기기의 암호화된 개인키 조회 (키 동기화용)"""
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        tags=['Device'],
        summary='기기의 암호화된 개인키 가져오기',
        description='''
        새 기기에서 로그인 시 기존 기기의 암호화된 개인키를 가져옵니다.
        보안: 
        - 주 기기(is_primary)는 항상 키를 가져올 수 있습니다.
        - 그 외 기기는 최근 24시간 이내에 활성화된 경우만 허용됩니다.
        ''',
        responses={
            200: DevicePrivateKeyResponseSerializer,
            403: OpenApiResponse(description='보안상 접근 불가 (비활성 기기)'),
            404: OpenApiResponse(description='기기를 찾을 수 없음'),
        }
    )
    def get(self, request, device_id):
        """특정 기기의 암호화된 개인키 가져오기"""
        from datetime import timedelta

        from django.utils import timezone
        
        try:
            device = UserDevice.objects.get(id=device_id, user=request.user)
        except UserDevice.DoesNotExist:
            return Response(
                {'error': '기기를 찾을 수 없습니다.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # 보안: 주 기기는 항상 허용, 그 외는 최근 활동이 있는 기기만 허용 (24시간 이내)
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
    """사용자의 기기 공개 정보 조회 (다른 사용자가 조회)"""
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
        description='''
        회원 탈퇴를 진행합니다.
        
        주의사항:
        - 모든 데이터가 영구적으로 삭제됩니다 (채팅, 친구, 기기 등)
        - 삭제된 데이터는 복구할 수 없습니다
        - 비밀번호 확인과 "회원탈퇴" 문구 입력이 필요합니다
        ''',
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
        
        # 1. 모든 Refresh Token 삭제 (모든 기기에서 로그아웃)
        RefreshTokenStorage.delete_all_user_tokens(user_id)
        
        # 2. 사용자 삭제 (CASCADE로 연관 데이터 자동 삭제)
        # - UserDevice (기기)
        # - ChatRoomMember (채팅방 멤버십)
        # - Message (메시지 - sender가 null로 변경됨)
        # - Friend (친구 관계)
        # - ChatFolder (채팅 폴더)
        # - GroupChatInvitation (그룹챗 초대)
        user.delete()
        
        return Response(
            {
                'message': '회원 탈퇴가 완료되었습니다. 그동안 이용해주셔서 감사합니다.'
            },
            status=status.HTTP_200_OK
        )

