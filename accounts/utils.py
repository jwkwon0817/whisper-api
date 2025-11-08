import json
import uuid
from typing import Optional

import redis
from django.conf import settings


class RefreshTokenStorage:
    """Redis를 사용한 Refresh Token 저장 및 관리"""
    
    @staticmethod
    def _get_redis_client():
        """Redis 클라이언트 반환"""
        # REDIS_URL이 있으면 URL로 연결, 없으면 개별 설정 사용
        if hasattr(settings, 'REDIS_URL') and settings.REDIS_URL:
            return redis.from_url(
                settings.REDIS_URL,
                decode_responses=True
            )
        else:
            return redis.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                db=settings.REDIS_DB,
                decode_responses=True
            )
    
    @staticmethod
    def save_refresh_token(user_id, refresh_token, expires_in_days=7):
        """Refresh Token을 Redis에 저장"""
        redis_client = RefreshTokenStorage._get_redis_client()
        key = f"refresh_token:{user_id}:{refresh_token}"
        expires_in_seconds = expires_in_days * 24 * 60 * 60
        
        token_data = {
            'user_id': user_id,
            'token': refresh_token,
        }
        
        try:
            redis_client.setex(key, expires_in_seconds, json.dumps(token_data))
            return True
        except Exception as e:
            print(f"Redis 저장 오류: {e}")
            return False
    
    @staticmethod
    def get_refresh_token(user_id, refresh_token):
        """Refresh Token 조회"""
        redis_client = RefreshTokenStorage._get_redis_client()
        key = f"refresh_token:{user_id}:{refresh_token}"
        
        try:
            data = redis_client.get(key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            print(f"Redis 조회 오류: {e}")
            return None
    
    @staticmethod
    def delete_refresh_token(user_id, refresh_token):
        """Refresh Token 삭제 (로그아웃)"""
        redis_client = RefreshTokenStorage._get_redis_client()
        key = f"refresh_token:{user_id}:{refresh_token}"
        
        try:
            redis_client.delete(key)
            return True
        except Exception as e:
            print(f"Redis 삭제 오류: {e}")
            return False
    
    @staticmethod
    def delete_all_user_tokens(user_id):
        """사용자의 모든 Refresh Token 삭제"""
        redis_client = RefreshTokenStorage._get_redis_client()
        pattern = f"refresh_token:{user_id}:*"
        
        try:
            keys = redis_client.keys(pattern)
            if keys:
                redis_client.delete(*keys)
            return True
        except Exception as e:
            print(f"Redis 일괄 삭제 오류: {e}")
            return False
    
    @staticmethod
    def is_token_valid(user_id, refresh_token):
        """Refresh Token 유효성 검사"""
        return RefreshTokenStorage.get_refresh_token(user_id, refresh_token) is not None


class PhoneVerificationStorage:
    """전화번호 인증 관리 (Redis 사용)"""
    
    @staticmethod
    def _get_redis_client():
        """Redis 클라이언트 반환"""
        if hasattr(settings, 'REDIS_URL') and settings.REDIS_URL:
            return redis.from_url(
                settings.REDIS_URL,
                decode_responses=True
            )
        else:
            return redis.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                db=settings.REDIS_DB,
                decode_responses=True
            )
    
    @staticmethod
    def save_verification_code(phone_number: str, code: str, expires_in_seconds: int = 300):
        """인증번호 저장 (기본 5분)"""
        redis_client = PhoneVerificationStorage._get_redis_client()
        key = f"verification_code:{phone_number}"
        
        try:
            redis_client.setex(key, expires_in_seconds, code)
            return True
        except Exception as e:
            print(f"인증번호 저장 오류: {e}")
            return False
    
    @staticmethod
    def get_verification_code(phone_number: str) -> Optional[str]:
        """인증번호 조회"""
        redis_client = PhoneVerificationStorage._get_redis_client()
        key = f"verification_code:{phone_number}"
        
        try:
            return redis_client.get(key)
        except Exception as e:
            print(f"인증번호 조회 오류: {e}")
            return None
    
    @staticmethod
    def delete_verification_code(phone_number: str):
        """인증번호 삭제"""
        redis_client = PhoneVerificationStorage._get_redis_client()
        key = f"verification_code:{phone_number}"
        
        try:
            redis_client.delete(key)
            return True
        except Exception as e:
            print(f"인증번호 삭제 오류: {e}")
            return False
    
    @staticmethod
    def increment_attempts(phone_number: str, expires_in_seconds: int = 3600) -> int:
        """시도 횟수 증가 (기본 1시간)"""
        redis_client = PhoneVerificationStorage._get_redis_client()
        key = f"verification_attempts:{phone_number}"
        
        try:
            attempts = redis_client.incr(key)
            if attempts == 1:
                redis_client.expire(key, expires_in_seconds)
            return attempts
        except Exception as e:
            print(f"시도 횟수 증가 오류: {e}")
            return 0
    
    @staticmethod
    def get_attempts(phone_number: str) -> int:
        """시도 횟수 조회"""
        redis_client = PhoneVerificationStorage._get_redis_client()
        key = f"verification_attempts:{phone_number}"
        
        try:
            attempts = redis_client.get(key)
            return int(attempts) if attempts else 0
        except Exception as e:
            print(f"시도 횟수 조회 오류: {e}")
            return 0
    
    @staticmethod
    def reset_attempts(phone_number: str):
        """시도 횟수 초기화"""
        redis_client = PhoneVerificationStorage._get_redis_client()
        key = f"verification_attempts:{phone_number}"
        
        try:
            redis_client.delete(key)
            return True
        except Exception as e:
            print(f"시도 횟수 초기화 오류: {e}")
            return False
    
    @staticmethod
    def save_verified_token(phone_number: str, token: str, expires_in_seconds: int = 600):
        """인증 완료 토큰 저장 (기본 10분)"""
        redis_client = PhoneVerificationStorage._get_redis_client()
        key = f"verified_phone:{phone_number}"
        
        try:
            redis_client.setex(key, expires_in_seconds, token)
            return True
        except Exception as e:
            print(f"인증 토큰 저장 오류: {e}")
            return False
    
    @staticmethod
    def get_verified_token(phone_number: str) -> Optional[str]:
        """인증 완료 토큰 조회"""
        redis_client = PhoneVerificationStorage._get_redis_client()
        key = f"verified_phone:{phone_number}"
        
        try:
            return redis_client.get(key)
        except Exception as e:
            print(f"인증 토큰 조회 오류: {e}")
            return None
    
    @staticmethod
    def delete_verified_token(phone_number: str):
        """인증 완료 토큰 삭제"""
        redis_client = PhoneVerificationStorage._get_redis_client()
        key = f"verified_phone:{phone_number}"
        
        try:
            redis_client.delete(key)
            return True
        except Exception as e:
            print(f"인증 토큰 삭제 오류: {e}")
            return False
    
    @staticmethod
    def check_rate_limit(phone_number: str, limit_seconds: int = 60) -> bool:
        """Rate Limit 확인 (같은 번호로 1분에 1회 제한)"""
        redis_client = PhoneVerificationStorage._get_redis_client()
        key = f"rate_limit:{phone_number}"
        
        try:
            exists = redis_client.exists(key)
            if exists:
                return False  # 제한 초과
            
            redis_client.setex(key, limit_seconds, "1")
            return True  # 허용
        except Exception as e:
            print(f"Rate Limit 확인 오류: {e}")
            return False

