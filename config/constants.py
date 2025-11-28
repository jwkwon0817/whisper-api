"""
프로젝트 전역 상수 정의

이 파일에서 하드코딩된 값들을 중앙 관리합니다.
"""

# MARK: - Authentication Constants

# Refresh Token 만료 기간 (일 단위)
REFRESH_TOKEN_EXPIRES_DAYS = 7

# 인증번호 만료 시간 (초 단위) - 5분
VERIFICATION_CODE_EXPIRES_SECONDS = 300

# 인증 완료 토큰 만료 시간 (초 단위) - 10분
VERIFIED_TOKEN_EXPIRES_SECONDS = 600


# MARK: - WebSocket Error Codes

# 토큰 없음
WEBSOCKET_ERROR_NO_TOKEN = 4001

# 사용자를 찾을 수 없음
WEBSOCKET_ERROR_USER_NOT_FOUND = 4002

# 유효하지 않은 토큰
WEBSOCKET_ERROR_INVALID_TOKEN = 4003

# 채팅방 멤버가 아님
WEBSOCKET_ERROR_NOT_MEMBER = 4004

