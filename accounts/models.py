import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.db import models

from utils.encryption import EncryptionService


class UserManager(BaseUserManager):
    def create_user(self, phone_number, password=None, **extra_fields):
        if not phone_number:
            raise ValueError('전화번호는 필수입니다.')
        
        # 전화번호 암호화 (복호화 가능)
        encrypted_phone = EncryptionService.encrypt_phone_number(phone_number)
        user = self.model(phone_number=encrypted_phone, **extra_fields)
        user.set_password(password)  # Django가 settings의 PASSWORD_HASHERS에 따라 bcrypt 사용
        user.save(using=self._db)
        return user
    
    def create_superuser(self, phone_number, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
        
        return self.create_user(phone_number, password, **extra_fields)
    
    def get_by_natural_key(self, username):
        """로그인 시 전화번호로 사용자 찾기 (암호화된 값 복호화 후 비교)"""
        # username은 원문 전화번호 (authenticate에서 전달됨)
        # 모든 사용자를 가져와서 복호화 후 비교
        # 주의: 사용자 수가 많을 경우 성능 이슈가 있을 수 있음
        users = self.all()
        for user in users:
            if EncryptionService.check_phone_number(username, user.phone_number):
                return user
        raise self.model.DoesNotExist()


class User(AbstractBaseUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, verbose_name='사용자 ID')
    phone_number = models.CharField(max_length=500, unique=True, verbose_name='전화번호 (암호화)')
    name = models.CharField(max_length=100, verbose_name='이름')
    profile_image = models.URLField(null=True, blank=True, verbose_name='프로필 사진 URL')
    public_key = models.TextField(null=True, blank=True, verbose_name='E2EE 공개키')
    
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    objects = UserManager()
    
    USERNAME_FIELD = 'phone_number'
    REQUIRED_FIELDS = ['name']
    
    class Meta:
        db_table = 'users'
        verbose_name = '사용자'
        verbose_name_plural = '사용자'
    
    def __str__(self):
        return f"{self.name} ({self.get_decrypted_phone_number()})"
    
    def get_decrypted_phone_number(self):
        """복호화된 전화번호 반환 (서버 내부용)"""
        return EncryptionService.decrypt_phone_number(self.phone_number)
    
    def get_masked_phone_number(self):
        """마스킹된 전화번호 반환 (프론트엔드용)"""
        decrypted = self.get_decrypted_phone_number()
        return EncryptionService.mask_phone_number(decrypted)
    
    def save(self, *args, **kwargs):
        """저장 시 전화번호 암호화"""
        # phone_number가 이미 암호화되어 있지 않은 경우에만 암호화
        if self.phone_number:
            # 암호화된 값인지 확인 (Fernet 암호화된 값은 특정 패턴을 가짐)
            try:
                # 복호화 시도해서 실패하면 암호화되지 않은 것으로 간주
                EncryptionService.decrypt_phone_number(self.phone_number)
            except:
                # 암호화되지 않은 경우 암호화
                self.phone_number = EncryptionService.encrypt_phone_number(self.phone_number)
        
        super().save(*args, **kwargs)
    
    def has_perm(self, perm, obj=None):
        return self.is_superuser
    
    def has_module_perms(self, app_label):
        return self.is_superuser


class Asset(models.Model):
    """S3에 업로드된 파일 정보를 저장하는 모델"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    s3_key = models.CharField(max_length=500, unique=True, verbose_name='S3 Key')
    original_name = models.CharField(max_length=255, verbose_name='원본 파일명')
    content_type = models.CharField(max_length=100, verbose_name='Content Type')
    file_size = models.BigIntegerField(verbose_name='파일 크기 (bytes)')
    url = models.URLField(verbose_name='파일 URL')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'assets'
        verbose_name = '에셋'
        verbose_name_plural = '에셋'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.original_name} ({self.s3_key})"

