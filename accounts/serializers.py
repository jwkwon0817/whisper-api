import re

from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from utils.s3_utils import S3Uploader

from .models import Asset, User
from .utils import PhoneVerificationStorage


class UserSerializer(serializers.ModelSerializer):
    """사용자 정보 시리얼라이저"""
    
    class Meta:
        model = User
        fields = ['id', 'phone_number', 'name', 'profile_image', 'public_key', 'created_at']
        read_only_fields = ['id', 'created_at']


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
        """전화번호 중복 확인"""
        if User.objects.filter(phone_number=value).exists():
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

