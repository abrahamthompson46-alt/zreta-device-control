from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("register/", views.RegisterView.as_view(), name="register"),
    path("login/", views.EmailLoginView.as_view(), name="login"),
    path("logout/", views.EmailLogoutView.as_view(), name="logout"),
    path("password/change/", views.ChangePasswordView.as_view(), name="password_change"),
    path("password/reset/", views.ResetPasswordView.as_view(), name="password_reset"),
    path("password/reset/done/", views.ResetPasswordDoneView.as_view(), name="password_reset_done"),
    path(
        "password/reset/<uidb64>/<token>/",
        views.ResetPasswordConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "password/reset/complete/",
        views.ResetPasswordCompleteView.as_view(),
        name="password_reset_complete",
    ),
    path("organizations/switch/", views.SwitchOrganizationView.as_view(), name="switch_organization"),
]
