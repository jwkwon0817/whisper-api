import base64

import bcrypt
from cryptography.fernet import Fernet
from django.conf import settings


class EncryptionService:
    """암호화/복호화 서비스"""
    
    # 개발 환경용 고정 키 (프로덕션에서는 절대 사용하지 말 것!)
    _DEV_KEY = None
    
    @staticmethod
    def _get_key():
        key = getattr(settings, 'ENCRYPTION_KEY', None)
        
        if not key:
            # 개발 환경에서는 고정된 키 사용 (일관성 유지)
            if settings.DEBUG:
                if EncryptionService._DEV_KEY is None:
                    EncryptionService._DEV_KEY = Fernet.generate_key()
                    print(f"[DEBUG] 개발 환경용 암호화 키 생성: {EncryptionService._DEV_KEY.decode()}")
                    print("[DEBUG] 이 키를 .env 파일의 ENCRYPTION_KEY에 설정하세요!")
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
        """
        전화번호 암호화 (Fernet 사용, 복호화 가능)
        
        Args:
            phone_number: 암호화할 전화번호
        
        Returns:
            str: 암호화된 전화번호
        """
        if not phone_number:
            return phone_number
        
        return EncryptionService.encrypt(phone_number)
    
    @staticmethod
    def decrypt_phone_number(encrypted_phone: str) -> str:
        """
        전화번호 복호화
        
        Args:
            encrypted_phone: 암호화된 전화번호
        
        Returns:
            str: 복호화된 전화번호
        """
        if not encrypted_phone:
            return encrypted_phone
        
        return EncryptionService.decrypt(encrypted_phone)
    
    @staticmethod
    def check_phone_number(phone_number: str, encrypted_phone: str) -> bool:
        """
        전화번호 검증 (암호화된 값 복호화 후 비교)
        
        Args:
            phone_number: 검증할 원문 전화번호
            encrypted_phone: 저장된 암호화된 전화번호
        
        Returns:
            bool: 일치 여부
        """
        if not phone_number or not encrypted_phone:
            return False
        
        try:
            decrypted = EncryptionService.decrypt_phone_number(encrypted_phone)
            return decrypted == phone_number
        except Exception:
            return False
    
    @staticmethod
    def encrypt(data: str) -> str:
        """
        데이터 암호화
        
        Args:
            data: 암호화할 문자열
        
        Returns:
            str: 암호화된 문자열 (base64 인코딩)
        """
        if not data:
            return data
        
        key = EncryptionService._get_key()
        fernet = Fernet(key)
        encrypted = fernet.encrypt(data.encode())
        return base64.urlsafe_b64encode(encrypted).decode()
    
    @staticmethod
    def decrypt(encrypted_data: str) -> str:
        """
        데이터 복호화
        
        Args:
            encrypted_data: 암호화된 문자열 (base64 인코딩)
        
        Returns:
            str: 복호화된 문자열
        """
        if not encrypted_data:
            return encrypted_data
        
        try:
            key = EncryptionService._get_key()
            fernet = Fernet(key)
            decoded = base64.urlsafe_b64decode(encrypted_data.encode())
            decrypted = fernet.decrypt(decoded)
            return decrypted.decode()
        except Exception as e:
            # 복호화 실패 시 원본 반환 (마이그레이션 호환성)
            return encrypted_data
    
    @staticmethod
    def mask_phone_number(phone_number: str) -> str:
        """
        전화번호 마스킹 (프론트엔드 표시용)
        
        Args:
            phone_number: 전화번호
        
        Returns:
            str: 마스킹된 전화번호 (예: 010****5678)
        """
        if not phone_number or len(phone_number) < 4:
            return phone_number
        
        # 앞 3자리와 뒤 4자리만 보여주고 나머지는 마스킹
        return f"{phone_number[:3]}****{phone_number[-4:]}"

