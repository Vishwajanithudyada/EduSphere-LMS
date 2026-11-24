
from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import RegisterView, LoginView, LogoutView


urlpatterns = [
    path(
        "register/",
        RegisterView.as_view(),
        name="account-register",
    ),

    path(
        "token/",
        LoginView.as_view(),
        name="token-obtain-pair",
    ),

    path(
        "token/refresh/",
        TokenRefreshView.as_view(),
        name="token-refresh",
    ),

    path(
        "logout/",
        LogoutView.as_view(),
        name="account-logout",
    ),
]
