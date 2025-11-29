import base64

from cryptography.fernet import Fernet
from django.conf import settings


class EncryptionService:
    _DEV_KEY = None
    
    @staticmethod
    def _get_key():
        key = getattr(settings, 'ENCRYPTION_KEY', None)
        
        if not key:
            if settings.DEBUG:
                if EncryptionService._DEV_KEY is None:
                    EncryptionService._DEV_KEY = Fernet.generate_key()
                key = EncryptionService._DEV_KEY
            else:
                raise ValueError("ENCRYPTION_KEY 환경변수가 설정되지 않았습니다.")
        else:
            pass
        
        if isinstance(key, str):
            key = key.encode()
        
        return key
    
    @staticmethod
    def encrypt_phone_number(phone_number: str) -> str:
        if not phone_number:
            return phone_number
        
        return EncryptionService.encrypt(phone_number)
    
    @staticmethod
    def decrypt_phone_number(encrypted_phone: str) -> str:
        if not encrypted_phone:
            return encrypted_phone
        
        return EncryptionService.decrypt(encrypted_phone)
    
    @staticmethod
    def check_phone_number(phone_number: str, encrypted_phone: str) -> bool:
        if not phone_number or not encrypted_phone:
            return False
        
        try:
            decrypted = EncryptionService.decrypt_phone_number(encrypted_phone)
            return decrypted == phone_number
        except Exception:
            return False
    
    @staticmethod
    def encrypt(data: str) -> str:
        if not data:
            return data
        
        key = EncryptionService._get_key()
        fernet = Fernet(key)
        encrypted = fernet.encrypt(data.encode())
        return base64.urlsafe_b64encode(encrypted).decode()
    
    @staticmethod
    def decrypt(encrypted_data: str) -> str:
        if not encrypted_data:
            return encrypted_data
        
        try:
            key = EncryptionService._get_key()
            fernet = Fernet(key)
            decoded = base64.urlsafe_b64decode(encrypted_data.encode())
            decrypted = fernet.decrypt(decoded)
            return decrypted.decode()
        except Exception:
            return encrypted_data
    
    @staticmethod
    def mask_phone_number(phone_number: str) -> str:
        if not phone_number or len(phone_number) < 4:
            return phone_number
        
        return f"{phone_number[:3]}****{phone_number[-4:]}"

