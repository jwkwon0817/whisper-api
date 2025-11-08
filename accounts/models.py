import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.db import models


class UserManager(BaseUserManager):
    def create_user(self, phone_number, password=None, **extra_fields):
        if not phone_number:
            raise ValueError('전화번호는 필수입니다.')
        
        user = self.model(phone_number=phone_number, **extra_fields)
        user.set_password(password)
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


class User(AbstractBaseUser):
    phone_number = models.CharField(max_length=20, unique=True, verbose_name='전화번호')
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
        return f"{self.name} ({self.phone_number})"
    
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

