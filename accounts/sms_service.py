import random
from typing import Dict, Optional

from django.conf import settings
from solapi import SolapiMessageService
from solapi.model import RequestMessage


class SolapiService:
    """Solapi SMS 발송 서비스 유틸리티"""
    
    def __init__(self):
        self.api_key = settings.SOLAPI_API_KEY
        self.api_secret = settings.SOLAPI_API_SECRET
        self.sender = settings.SOLAPI_SENDER_NUMBER
        self.message_service = SolapiMessageService(
            api_key=self.api_key,
            api_secret=self.api_secret
        )
    
    def send_sms(self, to: str, message: str) -> Dict:
        """
        SMS 발송
        
        Args:
            to: 수신자 전화번호 (01012345678 형식)
            message: 발송할 메시지
        
        Returns:
            Dict: 발송 결과
        """
        try:
            # RequestMessage 객체 생성
            request_message = RequestMessage(
                from_=self.sender,
                to=to,
                text=message
            )
            
            response = self.message_service.send(request_message)
            
            return {
                'success': True,
                'data': {
                    'group_id': response.group_info.group_id,
                    'total': response.group_info.count.total,
                    'registered_success': response.group_info.count.registered_success,
                    'registered_failed': response.group_info.count.registered_failed,
                }
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def send_verification_code(self, phone_number: str, code: str) -> Dict:
        """
        인증번호 SMS 발송
        
        Args:
            phone_number: 전화번호
            code: 인증번호
        
        Returns:
            Dict: 발송 결과
        """
        message = f"[Whisper] 인증번호는 {code}입니다. 5분간 유효합니다."
        return self.send_sms(phone_number, message)
    
    @staticmethod
    def generate_verification_code(length: int = 6) -> str:
        """
        인증번호 생성
        
        Args:
            length: 인증번호 길이 (기본 6자리)
        
        Returns:
            str: 인증번호
        """
        return ''.join([str(random.randint(0, 9)) for _ in range(length)])

