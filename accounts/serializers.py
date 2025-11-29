import re

from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from utils.s3_utils import S3Uploader

from .models import User, UserDevice
from .utils import PhoneVerificationStorage


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    phone_number = serializers.CharField()
    device_fingerprint = serializers.CharField(required=False, allow_blank=True, 
                                               help_text='기기 지문 (선택사항, 기존 기기 확인용)')
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'username' in self.fields:
            del self.fields['username']
    
    def validate(self, attrs):
        phone_number = attrs.get('phone_number')
        password = attrs.get('password')
        device_fingerprint = attrs.get('device_fingerprint', '').strip()
        
        if not phone_number or not password:
            raise serializers.ValidationError({
                'phone_number': '전화번호와 비밀번호를 입력해주세요.'
            })
        
        user = authenticate(
            request=self.context.get('request'),
            username=phone_number, 
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
        
        refresh = self.get_token(user)
        
        data = {}
        data['refresh'] = str(refresh)
        data['access'] = str(refresh.access_token)
        
        device_registered = False
        device_id = None
        
        if device_fingerprint:
            try:
                device = UserDevice.objects.get(
                    user=user,
                    device_fingerprint=device_fingerprint
                )
                device.save()  
                device_registered = True
                device_id = device.id
            except UserDevice.DoesNotExist:
                device_registered = False
                device_id = None
        
        data['device_registered'] = device_registered
        data['device_id'] = str(device_id) if device_id else None
        
        return data


class UserSerializer(serializers.ModelSerializer):
    masked_phone_number = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = ['id', 'name', 'profile_image', 'public_key', 'masked_phone_number', 'created_at']
        read_only_fields = ['id', 'created_at', 'masked_phone_number']
    
    def get_masked_phone_number(self, obj: User) -> str:
        return obj.get_masked_phone_number()


class PhoneVerificationSerializer(serializers.Serializer):
    phone_number = serializers.CharField(required=True, max_length=20)
    
    def validate_phone_number(self, value):
        pattern = r'^01[0-9]{9}$'
        if not re.match(pattern, value):
            raise serializers.ValidationError("올바른 전화번호 형식이 아닙니다. (예: 01012345678)")
        return value


class PhoneVerifySerializer(serializers.Serializer):
    phone_number = serializers.CharField(required=True, max_length=20)
    code = serializers.CharField(required=True, max_length=6, min_length=6)
    
    def validate_phone_number(self, value):
        pattern = r'^01[0-9]{9}$'
        if not re.match(pattern, value):
            raise serializers.ValidationError("올바른 전화번호 형식이 아닙니다.")
        return value
    
    def validate_code(self, value):
        if not value.isdigit():
            raise serializers.ValidationError("인증번호는 숫자만 입력 가능합니다.")
        return value


class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True, validators=[validate_password])
    profile_image = serializers.ImageField(required=False, allow_null=True)
    verified_token = serializers.CharField(required=True, write_only=True)
    public_key = serializers.CharField(required=False, allow_blank=True, allow_null=True, 
                                       help_text='E2EE 공개키 (PEM 형식). 선택사항이며 나중에 프로필 수정으로 추가 가능합니다.')
    device_name = serializers.CharField(
        required=False, 
        allow_blank=True, 
        max_length=100,
        help_text='기기 이름 (예: iPhone 14, Chrome on MacBook). 제공하면 첫 기기로 등록됩니다.'
    )
    device_fingerprint = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=255,
        help_text='기기 지문 (고유 식별자). device_name과 함께 제공되어야 합니다.'
    )
    encrypted_private_key = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text='암호화된 개인키 (JSON 문자열). device_name과 함께 제공되어야 합니다.'
    )
    
    class Meta:
        model = User
        fields = ['phone_number', 'name', 'password', 'profile_image', 'verified_token', 'public_key',
                  'device_name', 'device_fingerprint', 'encrypted_private_key']
        extra_kwargs = {
            'profile_image': {'required': False},
            'public_key': {'required': False},
            'device_name': {'required': False},
            'device_fingerprint': {'required': False},
            'encrypted_private_key': {'required': False},
        }
    
    def validate_verified_token(self, value):
        phone_number = self.initial_data.get('phone_number')
        if not phone_number:
            raise serializers.ValidationError("전화번호가 필요합니다.")
        
        stored_token = PhoneVerificationStorage.get_verified_token(phone_number)
        if not stored_token or stored_token != value:
            raise serializers.ValidationError("인증되지 않은 전화번호입니다. 인증을 먼저 완료해주세요.")
        
        return value
    
    def validate_phone_number(self, value):
        from utils.encryption import EncryptionService

        for user in User.objects.all():
            if EncryptionService.check_phone_number(value, user.phone_number):
                raise serializers.ValidationError("이미 가입된 전화번호입니다.")
        return value
    
    def validate_public_key(self, value):
        if not value:
            return value
        
        if not value.startswith('-----BEGIN PUBLIC KEY-----'):
            raise serializers.ValidationError("공개키는 PEM 형식이어야 합니다.")
        if not value.endswith('-----END PUBLIC KEY-----'):
            raise serializers.ValidationError("공개키는 PEM 형식이어야 합니다.")
        
        return value
    
    def validate(self, attrs):
        device_name = attrs.get('device_name')
        device_fingerprint = attrs.get('device_fingerprint')
        encrypted_private_key = attrs.get('encrypted_private_key')
        
        device_fields = [device_name, device_fingerprint, encrypted_private_key]
        provided_fields = [f for f in device_fields if f]
        
        if len(provided_fields) > 0 and len(provided_fields) < 3:
            raise serializers.ValidationError(
                '기기를 등록하려면 device_name, device_fingerprint, encrypted_private_key를 모두 제공해야 합니다.'
            )
        
        if device_fingerprint and UserDevice.objects.filter(device_fingerprint=device_fingerprint).exists():
            raise serializers.ValidationError({'device_fingerprint': '이미 등록된 기기입니다.'})
        
        return attrs
    
    def create(self, validated_data):
        verified_token = validated_data.pop('verified_token')
        phone_number = validated_data.get('phone_number')
        profile_image_file = validated_data.pop('profile_image', None)
        password = validated_data.pop('password')
        
        device_name = validated_data.pop('device_name', None)
        device_fingerprint = validated_data.pop('device_fingerprint', None)
        encrypted_private_key = validated_data.pop('encrypted_private_key', None)
        
        stored_token = PhoneVerificationStorage.get_verified_token(phone_number)
        if not stored_token or stored_token != verified_token:
            raise serializers.ValidationError({'verified_token': '인증 토큰이 유효하지 않습니다.'})
        
        PhoneVerificationStorage.delete_verified_token(phone_number)
        
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
        
        user = User.objects.create_user(
            password=password,
            profile_image=profile_image_url,
            **validated_data
        )
        
        if device_name and device_fingerprint and encrypted_private_key:
            UserDevice.objects.create(
                user=user,
                device_name=device_name,
                device_fingerprint=device_fingerprint,
                encrypted_private_key=encrypted_private_key,
                is_primary=True
            )
        
        return user


class PublicKeySerializer(serializers.Serializer):
    public_key = serializers.CharField(
        required=True,
        help_text='E2EE 공개키 (PEM 형식)'
    )
    
    def validate_public_key(self, value):
        if not value:
            raise serializers.ValidationError("공개키는 필수입니다.")
        
        if not value.startswith('-----BEGIN PUBLIC KEY-----'):
            raise serializers.ValidationError("공개키는 PEM 형식이어야 합니다.")
        if not value.endswith('-----END PUBLIC KEY-----'):
            raise serializers.ValidationError("공개키는 PEM 형식이어야 합니다.")
        
        return value


class UserUpdateSerializer(serializers.ModelSerializer):
    profile_image = serializers.ImageField(required=False, allow_null=True)
    
    class Meta:
        model = User
        fields = ['name', 'profile_image', 'public_key']
    
    def validate_public_key(self, value):
        if not value:
            return value
        
        if not value.startswith('-----BEGIN PUBLIC KEY-----'):
            raise serializers.ValidationError("공개키는 PEM 형식이어야 합니다.")
        if not value.endswith('-----END PUBLIC KEY-----'):
            raise serializers.ValidationError("공개키는 PEM 형식이어야 합니다.")
        
        return value
    
    def update(self, instance, validated_data):
        profile_image_file = validated_data.pop('profile_image', None)
        
        if profile_image_file:
            uploader = S3Uploader()
            try:
                if instance.profile_image:
                    pass
                
                asset, profile_image_url = uploader.upload_file(
                    profile_image_file,
                    folder='profiles',
                    content_type=profile_image_file.content_type
                )
                validated_data['profile_image'] = profile_image_url
            except Exception as e:
                raise serializers.ValidationError({'profile_image': f'이미지 업로드 실패: {str(e)}'})
        
        return super().update(instance, validated_data)


class DevUserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True, validators=[validate_password])
    profile_image = serializers.ImageField(required=False, allow_null=True)
    public_key = serializers.CharField(required=False, allow_blank=True, allow_null=True, 
                                       help_text='E2EE 공개키 (PEM 형식). 선택사항입니다.')
    device_name = serializers.CharField(required=False, allow_blank=True, max_length=100)
    device_fingerprint = serializers.CharField(required=False, allow_blank=True, max_length=255)
    encrypted_private_key = serializers.CharField(required=False, allow_blank=True)
    
    class Meta:
        model = User
        fields = ['phone_number', 'name', 'password', 'profile_image', 'public_key',
                  'device_name', 'device_fingerprint', 'encrypted_private_key']
        extra_kwargs = {
            'profile_image': {'required': False},
            'public_key': {'required': False},
            'device_name': {'required': False},
            'device_fingerprint': {'required': False},
            'encrypted_private_key': {'required': False},
        }
    
    def validate_phone_number(self, value):
        import re
        pattern = r'^01[0-9]{9}$'
        if not re.match(pattern, value):
            raise serializers.ValidationError("올바른 전화번호 형식이 아닙니다. (예: 01012345678)")
        
        from utils.encryption import EncryptionService
        for user in User.objects.all():
            if EncryptionService.check_phone_number(value, user.phone_number):
                raise serializers.ValidationError("이미 가입된 전화번호입니다.")
        return value
    
    def validate_public_key(self, value):
        if not value:
            return value
        
        if not value.startswith('-----BEGIN PUBLIC KEY-----'):
            raise serializers.ValidationError("공개키는 PEM 형식이어야 합니다.")
        if not value.endswith('-----END PUBLIC KEY-----'):
            raise serializers.ValidationError("공개키는 PEM 형식이어야 합니다.")
        
        return value
    
    def validate(self, attrs):
        device_name = attrs.get('device_name')
        device_fingerprint = attrs.get('device_fingerprint')
        encrypted_private_key = attrs.get('encrypted_private_key')
        
        device_fields = [device_name, device_fingerprint, encrypted_private_key]
        provided_fields = [f for f in device_fields if f]
        
        if len(provided_fields) > 0 and len(provided_fields) < 3:
            raise serializers.ValidationError(
                '기기를 등록하려면 device_name, device_fingerprint, encrypted_private_key를 모두 제공해야 합니다.'
            )
        
        if device_fingerprint and UserDevice.objects.filter(device_fingerprint=device_fingerprint).exists():
            raise serializers.ValidationError({'device_fingerprint': '이미 등록된 기기입니다.'})
        
        return attrs
    
    def create(self, validated_data):
        profile_image_file = validated_data.pop('profile_image', None)
        password = validated_data.pop('password')
        
        device_name = validated_data.pop('device_name', None)
        device_fingerprint = validated_data.pop('device_fingerprint', None)
        encrypted_private_key = validated_data.pop('encrypted_private_key', None)
        
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
        
        # 기기 정보가 제공되었으면 첫 기기로 등록
        if device_name and device_fingerprint and encrypted_private_key:
            UserDevice.objects.create(
                user=user,
                device_name=device_name,
                device_fingerprint=device_fingerprint,
                encrypted_private_key=encrypted_private_key,
                is_primary=True
            )
        
        return user


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


class UserDeviceSerializer(serializers.ModelSerializer):
    """사용자 기기 시리얼라이저"""
    
    class Meta:
        model = UserDevice
        fields = ['id', 'device_name', 'device_fingerprint', 'is_primary', 'last_active', 'created_at']
        read_only_fields = ['id', 'last_active', 'created_at']


class UserDeviceCreateSerializer(serializers.ModelSerializer):
    """기기 등록 시리얼라이저"""
    encrypted_private_key = serializers.CharField(
        required=True,
        help_text='비밀번호로 암호화된 개인키 (JSON 문자열)'
    )
    
    class Meta:
        model = UserDevice
        fields = ['device_name', 'device_fingerprint', 'encrypted_private_key']
    
    def validate_device_fingerprint(self, value):
        if UserDevice.objects.filter(device_fingerprint=value).exists():
            raise serializers.ValidationError("이미 등록된 기기입니다.")
        return value
    
    def create(self, validated_data):
        user = self.context['request'].user
        device = UserDevice.objects.create(
            user=user,
            **validated_data
        )
        return device


class UserDevicePrivateKeySerializer(serializers.Serializer):
    """암호화된 개인키 조회 시리얼라이저"""
    device_id = serializers.UUIDField(read_only=True)
    device_name = serializers.CharField(read_only=True)
    encrypted_private_key = serializers.CharField(read_only=True)
    
    class Meta:
        fields = ['device_id', 'device_name', 'encrypted_private_key']


class UserDeleteSerializer(serializers.Serializer):
    """회원 탈퇴 시리얼라이저"""
    password = serializers.CharField(
        required=True,
        write_only=True,
        help_text='본인 확인을 위한 비밀번호'
    )
    confirm_text = serializers.CharField(
        required=True,
        write_only=True,
        help_text='탈퇴 확인 문구: "회원탈퇴"'
    )
    
    def validate_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError("비밀번호가 올바르지 않습니다.")
        return value
    
    def validate_confirm_text(self, value):
        if value != '회원탈퇴':
            raise serializers.ValidationError('탈퇴 확인 문구가 올바르지 않습니다. "회원탈퇴"를 정확히 입력해주세요.')
        return value
