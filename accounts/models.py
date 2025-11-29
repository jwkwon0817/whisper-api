import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.db import models

from utils.encryption import EncryptionService


class UserManager(BaseUserManager):
    def create_user(self, phone_number, password=None, **extra_fields):
        if not phone_number:
            raise ValueError('전화번호는 필수입니다.')
        
        encrypted_phone = EncryptionService.encrypt_phone_number(phone_number)
        user = self.model(phone_number=encrypted_phone, **extra_fields)
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
    
    def get_by_natural_key(self, username):
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
        return EncryptionService.decrypt_phone_number(self.phone_number)
    
    def get_masked_phone_number(self):
        decrypted = self.get_decrypted_phone_number()
        return EncryptionService.mask_phone_number(decrypted)
    
    def save(self, *args, **kwargs):
        if self.phone_number:
            try:
                EncryptionService.decrypt_phone_number(self.phone_number)
            except:
                self.phone_number = EncryptionService.encrypt_phone_number(self.phone_number)
        
        super().save(*args, **kwargs)
    
    def has_perm(self, perm, obj=None):
        return self.is_superuser
    
    def has_module_perms(self, app_label):
        return self.is_superuser


class UserDevice(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='devices', verbose_name='사용자')
    device_name = models.CharField(max_length=100, verbose_name='기기 이름')
    device_fingerprint = models.CharField(max_length=255, unique=True, verbose_name='기기 지문')
    encrypted_private_key = models.TextField(verbose_name='암호화된 개인키 (JSON)')
    is_primary = models.BooleanField(default=False, verbose_name='주 기기 여부')
    last_active = models.DateTimeField(auto_now=True, verbose_name='마지막 활동 시간')
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'user_devices'
        verbose_name = '사용자 기기'
        verbose_name_plural = '사용자 기기'
        unique_together = [['user', 'device_fingerprint']]
        ordering = ['-last_active']
        indexes = [
            models.Index(fields=['user', 'is_primary']),
            models.Index(fields=['device_fingerprint']),
        ]
    
    def __str__(self):
        return f"{self.user.name}의 {self.device_name}"
    
    def save(self, *args, **kwargs):
        if not UserDevice.objects.filter(user=self.user).exists():
            self.is_primary = True
        super().save(*args, **kwargs)


