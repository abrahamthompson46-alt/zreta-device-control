from django.urls import path

from . import api

urlpatterns = [
    path("auth/register", api.RegisterAPIView.as_view(), name="api-register"),
    path("auth/login", api.LoginAPIView.as_view(), name="api-login"),
    path("auth/logout", api.LogoutAPIView.as_view(), name="api-logout"),
    path("auth/me", api.MeAPIView.as_view(), name="api-me"),
]
