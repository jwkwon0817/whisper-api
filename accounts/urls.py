from django.urls import path

from .views import (
                    CustomTokenObtainPairView,
                    CustomTokenRefreshView,
                    DeviceListView,
                    DevicePrivateKeyView,
                    LogoutView,
                    RegisterView,
                    SendVerificationCodeView,
                    UserDeleteView,
                    UserDevicesPublicView,
                    UserMeView,
                    UserPublicKeyView,
                    VerifyPhoneView,
)

urlpatterns = [
    path('auth/send-verification-code/', SendVerificationCodeView.as_view(), name='send-verification-code'),
    path('auth/verify-phone/', VerifyPhoneView.as_view(), name='verify-phone'),
    path('auth/register/', RegisterView.as_view(), name='register'),
    path('auth/login/', CustomTokenObtainPairView.as_view(), name='login'),
    path('auth/refresh/', CustomTokenRefreshView.as_view(), name='refresh'),
    path('auth/logout/', LogoutView.as_view(), name='logout'),
    
    path('me/', UserMeView.as_view(), name='me'),
    path('user/delete/', UserDeleteView.as_view(), name='user-delete'),
    path('users/<uuid:user_id>/public-key/', UserPublicKeyView.as_view(), name='user-public-key'),
    
    path('devices/', DeviceListView.as_view(), name='device-list'),
    path('devices/<uuid:device_id>/private-key/', DevicePrivateKeyView.as_view(), name='device-private-key'),
    path('users/<uuid:user_id>/devices/', UserDevicesPublicView.as_view(), name='user-devices-public'),
]

