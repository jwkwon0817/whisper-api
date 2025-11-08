import re

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from utils.encryption import EncryptionService
from utils.s3_utils import S3Uploader

from .models import Asset, User
from .utils import PhoneVerificationStorage


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """전화번호 원문으로 로그인할 수 있도록 하는 커스텀 serializer"""
    
    phone_number = serializers.CharField()
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'username' in self.fields:
            del self.fields['username']
    
    def validate(self, attrs):
        """전화번호를 암호화하여 사용자 검색 및 인증"""
        phone_number = attrs.get('phone_number')
        password = attrs.get('password')
        
        if not phone_number or not password:
            raise serializers.ValidationError({
                'phone_number': '전화번호와 비밀번호를 입력해주세요.'
            })
        
        # Django의 authenticate 함수 사용 (UserManager.get_by_natural_key 활용)
        # authenticate는 username과 password를 받아서 사용자를 찾고 비밀번호를 확인합니다
        # 우리의 경우 username이 phone_number이므로, 원문 전화번호를 그대로 전달
        user = authenticate(
            request=self.context.get('request'),
            username=phone_number,  # 원문 전화번호 전달
            password=password
        )
        
        if not user:
            raise serializers.ValidationError({
                'phone_number': '전화번호 또는 비밀번호가 올바르지 않습니다.'
            })
        
        if not user.is_active:
            raise serializers.ValidationError({
                'phone_number': '비활성화된 계정입니다.'
            })
        
        # 토큰 생성 (부모 클래스의 get_token 메서드 사용)
        refresh = self.get_token(user)
        
        # 부모 클래스의 validate 메서드가 반환하는 형식과 동일하게 반환
        data = {}
        data['refresh'] = str(refresh)
        data['access'] = str(refresh.access_token)
        
        return data


class UserSerializer(serializers.ModelSerializer):
    """사용자 정보 시리얼라이저"""
    masked_phone_number = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = ['id', 'name', 'profile_image', 'public_key', 'masked_phone_number', 'created_at']
        read_only_fields = ['id', 'created_at', 'masked_phone_number']
    
    def get_masked_phone_number(self, obj):
        """마스킹된 전화번호 반환"""
        return obj.get_masked_phone_number()


class PhoneVerificationSerializer(serializers.Serializer):
    """인증번호 전송 시리얼라이저"""
    phone_number = serializers.CharField(required=True, max_length=20)
    
    def validate_phone_number(self, value):
        """전화번호 형식 검증"""
        # 한국 전화번호 형식: 01012345678
        pattern = r'^01[0-9]{9}$'
        if not re.match(pattern, value):
            raise serializers.ValidationError("올바른 전화번호 형식이 아닙니다. (예: 01012345678)")
        return value


class PhoneVerifySerializer(serializers.Serializer):
    """인증번호 검증 시리얼라이저"""
    phone_number = serializers.CharField(required=True, max_length=20)
    code = serializers.CharField(required=True, max_length=6, min_length=6)
    
    def validate_phone_number(self, value):
        """전화번호 형식 검증"""
        pattern = r'^01[0-9]{9}$'
        if not re.match(pattern, value):
            raise serializers.ValidationError("올바른 전화번호 형식이 아닙니다.")
        return value
    
    def validate_code(self, value):
        """인증번호 형식 검증"""
        if not value.isdigit():
            raise serializers.ValidationError("인증번호는 숫자만 입력 가능합니다.")
        return value


class UserRegistrationSerializer(serializers.ModelSerializer):
    """회원가입 시리얼라이저"""
    password = serializers.CharField(write_only=True, required=True, validators=[validate_password])
    profile_image = serializers.ImageField(required=False, allow_null=True)
    verified_token = serializers.CharField(required=True, write_only=True)
    
    class Meta:
        model = User
        fields = ['phone_number', 'name', 'password', 'profile_image', 'verified_token']
        extra_kwargs = {
            'profile_image': {'required': False}
        }
    
    def validate_verified_token(self, value):
        """인증 토큰 검증"""
        phone_number = self.initial_data.get('phone_number')
        if not phone_number:
            raise serializers.ValidationError("전화번호가 필요합니다.")
        
        stored_token = PhoneVerificationStorage.get_verified_token(phone_number)
        if not stored_token or stored_token != value:
            raise serializers.ValidationError("인증되지 않은 전화번호입니다. 인증을 먼저 완료해주세요.")
        
        return value
    
    def validate_phone_number(self, value):
        """전화번호 중복 확인 (암호화된 값 복호화 후 비교)"""
        from utils.encryption import EncryptionService

        # 모든 사용자를 가져와서 복호화 후 비교
        for user in User.objects.all():
            if EncryptionService.check_phone_number(value, user.phone_number):
                raise serializers.ValidationError("이미 가입된 전화번호입니다.")
        return value
    
    def create(self, validated_data):
        verified_token = validated_data.pop('verified_token')
        phone_number = validated_data.get('phone_number')
        profile_image_file = validated_data.pop('profile_image', None)
        password = validated_data.pop('password')
        
        # 인증 토큰 재검증 및 삭제
        stored_token = PhoneVerificationStorage.get_verified_token(phone_number)
        if not stored_token or stored_token != verified_token:
            raise serializers.ValidationError({'verified_token': '인증 토큰이 유효하지 않습니다.'})
        
        PhoneVerificationStorage.delete_verified_token(phone_number)
        
        # 프로필 이미지가 있으면 S3에 업로드
        profile_image_url = None
        if profile_image_file:
            uploader = S3Uploader()
            try:
                asset, profile_image_url = uploader.upload_file(
                    profile_image_file,
                    folder='profiles',
                    content_type=profile_image_file.content_type
                )
            except Exception as e:
                raise serializers.ValidationError({'profile_image': f'이미지 업로드 실패: {str(e)}'})
        
        # 사용자 생성
        user = User.objects.create_user(
            password=password,
            profile_image=profile_image_url,
            **validated_data
        )
        return user


class UserUpdateSerializer(serializers.ModelSerializer):
    """사용자 정보 수정 시리얼라이저"""
    profile_image = serializers.ImageField(required=False, allow_null=True)
    
    class Meta:
        model = User
        fields = ['name', 'profile_image', 'public_key']
    
    def update(self, instance, validated_data):
        profile_image_file = validated_data.pop('profile_image', None)
        
        # 새 프로필 이미지가 있으면 S3에 업로드
        if profile_image_file:
            uploader = S3Uploader()
            try:
                # 기존 이미지가 있으면 Asset에서 찾아서 삭제 (선택사항)
                if instance.profile_image:
                    # URL에서 S3 key 추출하여 기존 파일 삭제 가능
                    pass
                
                # 새 이미지 업로드
                asset, profile_image_url = uploader.upload_file(
                    profile_image_file,
                    folder='profiles',
                    content_type=profile_image_file.content_type
                )
                validated_data['profile_image'] = profile_image_url
            except Exception as e:
                raise serializers.ValidationError({'profile_image': f'이미지 업로드 실패: {str(e)}'})
        
        return super().update(instance, validated_data)


class PasswordChangeSerializer(serializers.Serializer):
    """비밀번호 변경 시리얼라이저"""
    old_password = serializers.CharField(required=True, write_only=True)
    new_password = serializers.CharField(required=True, write_only=True, validators=[validate_password])
    new_password2 = serializers.CharField(required=True, write_only=True, label='새 비밀번호 확인')
    
    def validate(self, attrs):
        if attrs['new_password'] != attrs['new_password2']:
            raise serializers.ValidationError({"new_password": "새 비밀번호가 일치하지 않습니다."})
        return attrs
    
    def validate_old_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError("기존 비밀번호가 올바르지 않습니다.")
        return value
