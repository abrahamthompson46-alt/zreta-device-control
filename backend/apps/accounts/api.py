from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.services import record_audit, request_meta

from .authorization import SESSION_ORG_KEY
from .models import User
from .services import register_family_account


class RegisterAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        email = (request.data.get("email") or "").strip().lower()
        password = request.data.get("password") or ""
        organization_name = request.data.get("organization_name") or ""
        if not email or not password:
            return Response({"detail": "email and password are required"}, status=400)
        if User.objects.filter(email__iexact=email).exists():
            return Response({"detail": "A user with this email already exists."}, status=400)
        try:
            validate_password(password)
        except ValidationError as exc:
            return Response({"detail": exc.messages}, status=400)
        user, organization, membership = register_family_account(
            email=email,
            password=password,
            organization_name=organization_name,
        )
        login(request, user)
        request.session[SESSION_ORG_KEY] = str(organization.id)
        return Response(
            {
                "user": {"id": str(user.id), "email": user.email},
                "organization": {
                    "id": str(organization.id),
                    "name": organization.name,
                    "type": organization.type,
                },
                "role": membership.role,
            },
            status=status.HTTP_201_CREATED,
        )


class LoginAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = (request.data.get("email") or "").strip()
        password = request.data.get("password") or ""
        user = authenticate(request, username=email, password=password)
        membership = None
        from .models import Membership

        if email:
            membership = (
                Membership.objects.select_related("organization", "user")
                .filter(user__email__iexact=email)
                .first()
            )
        if user is None:
            if membership:
                record_audit(
                    organization=membership.organization,
                    actor_user=membership.user,
                    action="user.login",
                    result="failure",
                    **request_meta(request),
                )
            return Response({"detail": "Invalid credentials."}, status=400)
        login(request, user)
        if membership:
            request.session[SESSION_ORG_KEY] = str(membership.organization_id)
            record_audit(
                organization=membership.organization,
                actor_user=user,
                action="user.login",
                result="success",
                **request_meta(request),
            )
        return Response({"email": user.email, "id": str(user.id)})


class LogoutAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        logout(request)
        return Response({"detail": "Logged out."})


class MeAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        membership = getattr(request, "membership", None)
        return Response(
            {
                "id": str(request.user.id),
                "email": request.user.email,
                "is_active": request.user.is_active,
                "mfa_enabled": request.user.mfa_enabled,
                "organization": (
                    {
                        "id": str(membership.organization_id),
                        "name": membership.organization.name,
                        "type": membership.organization.type,
                        "role": membership.role,
                    }
                    if membership
                    else None
                ),
            }
        )
