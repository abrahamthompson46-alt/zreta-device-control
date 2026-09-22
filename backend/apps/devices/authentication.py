from __future__ import annotations

from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import BasePermission

from apps.devices.crypto import DeviceAuthError, decode_device_access_token
from apps.devices.models import CredentialStatus, Device, DeviceCredential


class DeviceActor:
    """DRF-authenticated principal representing an enrolled device, not a parent User."""

    is_authenticated = True
    is_anonymous = False
    pk = None

    def __init__(self, device: Device, credential: DeviceCredential):
        self.device = device
        self.credential = credential
        self.pk = device.pk
        self.id = device.id

    def __str__(self) -> str:
        return str(self.device_id)

    @property
    def device_id(self):
        return self.device.id


class DeviceJWTAuthentication(BaseAuthentication):
    def authenticate(self, request):
        header = request.META.get("HTTP_AUTHORIZATION") or ""
        if not header.startswith("Bearer "):
            return None
        raw = header[7:].strip()
        if not raw:
            return None
        try:
            claims = decode_device_access_token(raw)
        except DeviceAuthError as exc:
            raise AuthenticationFailed(str(exc)) from exc
        if claims.get("token_use") != "device_access":
            raise AuthenticationFailed("Wrong token type.")
        device = (
            Device.objects.select_related("organization", "status")
            .filter(pk=claims.get("sub"), is_active=True)
            .first()
        )
        if device is None:
            raise AuthenticationFailed("Device is unknown or revoked.")
        credential = device.credentials.filter(
            public_key_id=claims.get("kid"),
            status=CredentialStatus.ACTIVE,
        ).first()
        if credential is None:
            raise AuthenticationFailed("Device credential is revoked or rotated.")
        credential.last_used_at = timezone.now()
        credential.save(update_fields=["last_used_at"])
        request.device = device
        request.device_credential = credential
        return (DeviceActor(device, credential), raw)


class IsEnrolledDevice(BasePermission):
    def has_permission(self, request, view):
        return isinstance(getattr(request, "user", None), DeviceActor)
