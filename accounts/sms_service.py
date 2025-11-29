import random
from typing import Dict

from django.conf import settings
from solapi import SolapiMessageService
from solapi.model import RequestMessage


class SolapiService:
    def __init__(self):
        self.api_key = settings.SOLAPI_API_KEY
        self.api_secret = settings.SOLAPI_API_SECRET
        self.sender = settings.SOLAPI_SENDER_NUMBER
        self.message_service = SolapiMessageService(
            api_key=self.api_key,
            api_secret=self.api_secret
        )
    
    def send_sms(self, to: str, message: str) -> Dict:
        try:
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
        message = f"[Whisper] 인증번호는 {code}입니다. 5분간 유효합니다."
        return self.send_sms(phone_number, message)
    
    @staticmethod
    def generate_verification_code(length: int = 6) -> str:
        return ''.join([str(random.randint(0, 9)) for _ in range(length)])

