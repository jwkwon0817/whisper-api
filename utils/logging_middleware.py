"""
DEBUG 모드에서 모든 요청/응답을 로깅하는 미들웨어
"""

import json
import logging
import uuid
from datetime import datetime, date
from decimal import Decimal
from django.conf import settings
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger('api')


class RequestResponseLoggingMiddleware(MiddlewareMixin):
    """
    DEBUG 모드에서 모든 API 요청과 응답을 로깅
    """
    
    def process_request(self, request):
        """요청 시작 시 로깅"""
        if not settings.DEBUG:
            return
        
        # API 요청만 로깅 (/api/로 시작하는 경로)
        if not request.path.startswith('/api/'):
            return
        
        # 요청 정보 출력
        logger.info('='*80)
        logger.info(f'🔵 REQUEST: {request.method} {request.path}')
        logger.info('-'*80)
        
        # Query Parameters
        if request.GET:
            logger.info(f'📝 Query Params:')
            for key, value in request.GET.items():
                logger.info(f'   {key}: {value}')
        
        # Headers (민감한 정보 제외)
        logger.info(f'📋 Headers:')
        sensitive_headers = ['authorization', 'cookie', 'x-csrftoken']
        for header, value in request.headers.items():
            if header.lower() in sensitive_headers:
                # 토큰은 일부만 표시
                if header.lower() == 'authorization' and value.startswith('Bearer '):
                    token = value[7:]
                    masked_token = f"{token[:10]}...{token[-10:]}" if len(token) > 20 else "***"
                    logger.info(f'   {header}: Bearer {masked_token}')
                else:
                    logger.info(f'   {header}: ***')
            else:
                logger.info(f'   {header}: {value}')
        
        # Body (POST, PUT, PATCH)
        if request.method in ['POST', 'PUT', 'PATCH', 'DELETE']:
            try:
                if request.content_type == 'application/json':
                    body = json.loads(request.body.decode('utf-8'))
                    # 비밀번호 필드 마스킹
                    masked_body = self._mask_sensitive_data(body)
                    logger.info(f'📦 Body:')
                    logger.info(json.dumps(masked_body, indent=2, ensure_ascii=False))
                elif request.content_type and 'multipart/form-data' in request.content_type:
                    logger.info(f'📦 Body: multipart/form-data (파일 업로드)')
                    if request.POST:
                        masked_post = self._mask_sensitive_data(dict(request.POST))
                        logger.info(f'   Form Data: {masked_post}')
                    if request.FILES:
                        logger.info(f'   Files: {list(request.FILES.keys())}')
                else:
                    logger.info(f'📦 Body: {request.content_type}')
            except Exception as e:
                logger.info(f'📦 Body: (파싱 실패 - {str(e)})')
    
    def process_response(self, request, response):
        """응답 시 로깅"""
        if not settings.DEBUG:
            return response
        
        # API 요청만 로깅
        if not request.path.startswith('/api/'):
            return response
        
        # 응답 정보 출력
        status_emoji = self._get_status_emoji(response.status_code)
        logger.info('-'*80)
        logger.info(f'{status_emoji} RESPONSE: {response.status_code} {self._get_status_text(response.status_code)}')
        
        # Response Headers
        logger.info(f'📋 Response Headers:')
        for header, value in response.items():
            if header.lower() in ['set-cookie', 'authorization']:
                logger.info(f'   {header}: ***')
            else:
                logger.info(f'   {header}: {value}')
        
        # Response Body
        try:
            if hasattr(response, 'data'):
                # DRF Response
                masked_data = self._mask_sensitive_data(response.data)
                logger.info(f'📦 Response Body:')
                logger.info(json.dumps(masked_data, indent=2, ensure_ascii=False, default=self._json_serializer))
            elif response.get('Content-Type', '').startswith('application/json'):
                # JSON Response
                content = json.loads(response.content.decode('utf-8'))
                masked_content = self._mask_sensitive_data(content)
                logger.info(f'📦 Response Body:')
                logger.info(json.dumps(masked_content, indent=2, ensure_ascii=False, default=self._json_serializer))
            else:
                logger.info(f'📦 Response Body: ({response.get("Content-Type", "unknown")})')
        except Exception as e:
            logger.info(f'📦 Response Body: (파싱 실패 - {str(e)})')
        
        logger.info('='*80)
        logger.info('')  # 빈 줄 추가
        
        return response
    
    def _mask_sensitive_data(self, data):
        """민감한 데이터 마스킹"""
        if isinstance(data, dict):
            masked = {}
            for key, value in data.items():
                if key.lower() in ['password', 'old_password', 'new_password', 'new_password2']:
                    masked[key] = '***'
                elif key.lower() in ['access', 'refresh', 'token', 'verified_token']:
                    # 토큰은 일부만 표시
                    if isinstance(value, str) and len(value) > 20:
                        masked[key] = f"{value[:10]}...{value[-10:]}"
                    else:
                        masked[key] = '***'
                elif key.lower() in ['phone_number'] and isinstance(value, str):
                    # 전화번호 마스킹
                    if len(value) > 7:
                        masked[key] = f"{value[:3]}****{value[-4:]}"
                    else:
                        masked[key] = value
                elif key.lower() == 'encrypted_private_key':
                    masked[key] = '*** (encrypted)'
                elif isinstance(value, (uuid.UUID,)):
                    # UUID를 문자열로 변환
                    masked[key] = str(value)
                elif isinstance(value, dict):
                    masked[key] = self._mask_sensitive_data(value)
                elif isinstance(value, list):
                    masked[key] = [self._mask_sensitive_data(item) if isinstance(item, (dict, list)) else item for item in value]
                else:
                    masked[key] = value
            return masked
        elif isinstance(data, list):
            return [self._mask_sensitive_data(item) if isinstance(item, (dict, list)) else item for item in data]
        elif isinstance(data, uuid.UUID):
            # UUID를 문자열로 변환
            return str(data)
        else:
            return data
    
    def _json_serializer(self, obj):
        """JSON 직렬화를 위한 커스텀 직렬화 함수"""
        if isinstance(obj, uuid.UUID):
            return str(obj)
        elif isinstance(obj, (datetime, date)):
            return obj.isoformat()
        elif isinstance(obj, Decimal):
            return float(obj)
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
    
    def _get_status_emoji(self, status_code):
        """상태 코드에 따른 이모지"""
        if 200 <= status_code < 300:
            return '✅'
        elif 300 <= status_code < 400:
            return '↩️'
        elif 400 <= status_code < 500:
            return '⚠️'
        elif 500 <= status_code:
            return '❌'
        else:
            return '❓'
    
    def _get_status_text(self, status_code):
        """상태 코드 텍스트"""
        status_texts = {
            200: 'OK',
            201: 'Created',
            204: 'No Content',
            400: 'Bad Request',
            401: 'Unauthorized',
            403: 'Forbidden',
            404: 'Not Found',
            429: 'Too Many Requests',
            500: 'Internal Server Error',
        }
        return status_texts.get(status_code, 'Unknown')

