from django.urls import path

from .views import (CustomTokenObtainPairView, CustomTokenRefreshView,
                    DevRegisterView, DeviceDetailView, DeviceListView,
                    DevicePrivateKeyView, LogoutView, PasswordChangeView,
                    PublicKeyView, RegisterView, SendVerificationCodeView,
                    UserDeleteView, UserDevicesPublicView, UserMeView,
                    UserProfileView, UserPublicKeyView, UserSearchView,
                    VerifyPhoneView)

urlpatterns = [
    # 인증 관련
    path('auth/send-verification-code/', SendVerificationCodeView.as_view(), name='send-verification-code'),
    path('auth/verify-phone/', VerifyPhoneView.as_view(), name='verify-phone'),
    path('auth/register/', RegisterView.as_view(), name='register'),
    path('auth/register/dev/', DevRegisterView.as_view(), name='dev-register'),
    path('auth/login/', CustomTokenObtainPairView.as_view(), name='login'),
    path('auth/refresh/', CustomTokenRefreshView.as_view(), name='refresh'),
    path('auth/logout/', LogoutView.as_view(), name='logout'),
    
    # 사용자 정보
    path('me/', UserMeView.as_view(), name='me'),
    path('user/', UserProfileView.as_view(), name='user-update'),
    path('user/password/', PasswordChangeView.as_view(), name='password-change'),
    path('user/delete/', UserDeleteView.as_view(), name='user-delete'),
    path('user/public-key/', PublicKeyView.as_view(), name='public-key'),
    path('users/<uuid:user_id>/public-key/', UserPublicKeyView.as_view(), name='user-public-key'),
    path('users/search/', UserSearchView.as_view(), name='user-search'),
    
    # 기기 관리 (멀티 디바이스)
    path('devices/', DeviceListView.as_view(), name='device-list'),
    path('devices/<uuid:device_id>/', DeviceDetailView.as_view(), name='device-detail'),
    path('devices/<uuid:device_id>/private-key/', DevicePrivateKeyView.as_view(), name='device-private-key'),
    path('users/<uuid:user_id>/devices/', UserDevicesPublicView.as_view(), name='user-devices-public'),
]

