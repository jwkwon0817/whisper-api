from django.contrib.auth import get_user_model
from drf_spectacular.utils import (OpenApiParameter, OpenApiResponse,
                                   extend_schema)
from rest_framework import permissions, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import RefreshToken, UntypedToken
from rest_framework_simplejwt.views import (TokenObtainPairView,
                                            TokenRefreshView)

from .serializers import (CustomTokenObtainPairSerializer,
                          DevUserRegistrationSerializer,
                          PasswordChangeSerializer,
                          PhoneVerificationSerializer, PhoneVerifySerializer,
                          PublicKeySerializer, UserRegistrationSerializer,
                          UserSerializer, UserUpdateSerializer)
from .sms_service import SolapiService
from .utils import PhoneVerificationStorage, RefreshTokenStorage

User = get_user_model()


class CustomTokenObtainPairView(TokenObtainPairView):
    """로그인 시 Refresh Token을 Redis에 저장"""
    serializer_class = CustomTokenObtainPairSerializer
    
    @extend_schema(
        tags=['Auth'],
        summary='로그인',
        description='전화번호와 비밀번호로 로그인하고 JWT 토큰을 발급합니다.',
        request=CustomTokenObtainPairSerializer,
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
        description='새로운 사용자를 등록하고 JWT 토큰을 발급합니다. 전화번호 인증 완료 후 받은 verified_token이 필요합니다. profile_image는 선택사항이며 파일로 업로드할 수 있습니다.',
        request={
            'multipart/form-data': {
                'type': 'object',
                'properties': {
                    'phone_number': {'type': 'string', 'description': '전화번호 (예: 01012345678)'},
                    'name': {'type': 'string', 'description': '이름'},
                    'password': {'type': 'string', 'format': 'password', 'description': '비밀번호 (최소 8자)'},
                    'verified_token': {'type': 'string', 'description': '전화번호 인증 완료 토큰 (인증번호 검증 API에서 받은 토큰)'},
                    'profile_image': {'type': 'string', 'format': 'binary', 'description': '프로필 이미지 (선택사항)'},
                    'public_key': {'type': 'string', 'description': 'E2EE 공개키 (PEM 형식, 선택사항)'},
                },
                'required': ['phone_number', 'name', 'password', 'verified_token']
            },
            'application/json': UserRegistrationSerializer,
        },
        responses={
            201: OpenApiResponse(
                description='회원가입 성공',
                response={
                    'type': 'object',
                    'properties': {
                        'user': {'type': 'object'},
                        'access': {'type': 'string'},
                        'refresh': {'type': 'string'},
                    }
                }
            ),
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
            200: OpenApiResponse(
                description='로그아웃 성공',
                response={
                    'type': 'object',
                    'properties': {
                        'message': {'type': 'string'}
                    }
                }
            )
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
            200: OpenApiResponse(
                description='정보 변경 성공',
                response=UserUpdateSerializer
            ),
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
            200: OpenApiResponse(
                description='내 정보',
                response=UserSerializer
            ),
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
            200: OpenApiResponse(
                description='비밀번호 변경 성공',
                response={
                    'type': 'object',
                    'properties': {
                        'message': {'type': 'string'}
                    }
                }
            ),
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
            200: OpenApiResponse(
                description='공개키 등록 성공',
                response={
                    'type': 'object',
                    'properties': {
                        'message': {'type': 'string'},
                        'public_key': {'type': 'string'}
                    }
                }
            ),
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
            200: OpenApiResponse(
                description='공개키 조회 성공',
                response={
                    'type': 'object',
                    'properties': {
                        'user_id': {'type': 'string', 'format': 'uuid'},
                        'name': {'type': 'string'},
                        'public_key': {'type': 'string', 'nullable': True}
                    }
                }
            ),
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
            200: OpenApiResponse(
                description='검색 성공',
                response={
                    'type': 'object',
                    'properties': {
                        'results': {
                            'type': 'array',
                            'items': {
                                'type': 'object',
                                'properties': {
                                    'id': {'type': 'string', 'format': 'uuid'},
                                    'name': {'type': 'string'},
                                    'profile_image': {'type': 'string', 'nullable': True},
                                    'has_public_key': {'type': 'boolean'}
                                }
                            }
                        },
                        'count': {'type': 'integer'}
                    }
                }
            ),
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
            200: OpenApiResponse(
                description='인증번호 전송 성공',
                response={
                    'type': 'object',
                    'properties': {
                        'message': {'type': 'string'}
                    }
                }
            ),
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
            200: OpenApiResponse(
                description='인증 성공',
                response={
                    'type': 'object',
                    'properties': {
                        'message': {'type': 'string'},
                        'verified_token': {'type': 'string'},
                        'expires_in': {'type': 'integer'}
                    }
                }
            ),
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
        description='개발 모드에서 전화번호 인증 없이 회원가입합니다. DEBUG=True일 때만 사용 가능합니다.',
        request={
            'multipart/form-data': {
                'type': 'object',
                'properties': {
                    'phone_number': {'type': 'string', 'description': '전화번호 (예: 01012345678)'},
                    'name': {'type': 'string', 'description': '이름'},
                    'password': {'type': 'string', 'format': 'password', 'description': '비밀번호 (최소 8자)'},
                    'profile_image': {'type': 'string', 'format': 'binary', 'description': '프로필 이미지 (선택사항)'},
                    'public_key': {'type': 'string', 'description': 'E2EE 공개키 (PEM 형식, 선택사항)'},
                },
                'required': ['phone_number', 'name', 'password']
            },
            'application/json': DevUserRegistrationSerializer,
        },
        responses={
            201: OpenApiResponse(
                description='회원가입 성공',
                response={
                    'type': 'object',
                    'properties': {
                        'user': {'type': 'object'},
                        'access': {'type': 'string'},
                        'refresh': {'type': 'string'},
                    }
                }
            ),
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

