from django.urls import path

from .views import (CustomTokenObtainPairView, CustomTokenRefreshView,
                    DevRegisterView, LogoutView, PasswordChangeView,
                    PublicKeyView, RegisterView, SendVerificationCodeView,
                    UserMeView, UserProfileView, UserPublicKeyView,
                    UserSearchView, VerifyPhoneView)

urlpatterns = [
    path('auth/send-verification-code/', SendVerificationCodeView.as_view(), name='send-verification-code'),
    path('auth/verify-phone/', VerifyPhoneView.as_view(), name='verify-phone'),
    path('auth/register/', RegisterView.as_view(), name='register'),
    path('auth/register/dev/', DevRegisterView.as_view(), name='dev-register'),
    path('auth/login/', CustomTokenObtainPairView.as_view(), name='login'),
    path('auth/refresh/', CustomTokenRefreshView.as_view(), name='refresh'),
    path('auth/logout/', LogoutView.as_view(), name='logout'),
    
    path('me/', UserMeView.as_view(), name='me'),
    path('user/', UserProfileView.as_view(), name='user-update'),
    path('user/password/', PasswordChangeView.as_view(), name='password-change'),
    path('user/public-key/', PublicKeyView.as_view(), name='public-key'),
    path('users/<uuid:user_id>/public-key/', UserPublicKeyView.as_view(), name='user-public-key'),
    path('users/search/', UserSearchView.as_view(), name='user-search'),
]

