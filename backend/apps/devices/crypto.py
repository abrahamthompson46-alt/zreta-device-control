from __future__ import annotations

import uuid
from datetime import timedelta

import jwt
from cryptography.hazmat.primitives import serialization
from django.conf import settings
from django.utils import timezone
from jwt import InvalidTokenError

from apps.devices.models import DeviceAssertionJti, DeviceCredential


class DeviceAuthError(Exception):
    def __init__(self, message: str, code: str = "unauthorized"):
        super().__init__(message)
        self.code = code


def load_ec_public_key(pem: str):
    key = serialization.load_pem_public_key(pem.encode("utf-8"))
    return key


def issue_device_access_token(*, device, credential: DeviceCredential) -> tuple[str, int]:
    ttl = settings.DEVICE_ACCESS_TOKEN_TTL_SECONDS
    now = timezone.now()
    payload = {
        "iss": settings.DEVICE_JWT_ISSUER,
        "aud": settings.DEVICE_JWT_AUDIENCE,
        "sub": str(device.id),
        "org": str(device.organization_id),
        "kid": credential.public_key_id,
        "token_use": "device_access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl)).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
    return token, ttl


def decode_device_access_token(token: str) -> dict:
    try:
        return jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=["HS256"],
            audience=settings.DEVICE_JWT_AUDIENCE,
            issuer=settings.DEVICE_JWT_ISSUER,
            leeway=60,
        )
    except InvalidTokenError as exc:
        raise DeviceAuthError("Invalid or expired device token.", "invalid_token") from exc


def verify_client_assertion(*, device, credential: DeviceCredential, assertion: str) -> dict:
    """Verify an ES256 JWT signed by the device Keystore private key."""
    try:
        header = jwt.get_unverified_header(assertion)
    except InvalidTokenError as exc:
        raise DeviceAuthError("Malformed client assertion.", "invalid_assertion") from exc
    if header.get("alg") != "ES256":
        raise DeviceAuthError("Unsupported assertion algorithm.", "invalid_assertion")
    public_key = load_ec_public_key(credential.public_key)
    try:
        claims = jwt.decode(
            assertion,
            public_key,
            algorithms=["ES256"],
            audience=settings.DEVICE_JWT_AUDIENCE,
            leeway=60,
        )
    except InvalidTokenError as exc:
        raise DeviceAuthError("Invalid client assertion.", "invalid_assertion") from exc
    if claims.get("sub") != str(device.id) or claims.get("iss") != str(device.id):
        raise DeviceAuthError("Assertion device mismatch.", "invalid_assertion")
    if claims.get("kid") != credential.public_key_id:
        raise DeviceAuthError("Assertion key mismatch.", "invalid_assertion")
    jti = claims.get("jti")
    if not jti:
        raise DeviceAuthError("Assertion missing jti.", "invalid_assertion")
    exp = claims.get("exp")
    if not exp:
        raise DeviceAuthError("Assertion missing exp.", "invalid_assertion")
    max_age = settings.DEVICE_ASSERTION_TTL_SECONDS + 60
    now = timezone.now()
    if exp < int(now.timestamp()) or int(claims.get("iat", exp)) < int(now.timestamp()) - max_age:
        raise DeviceAuthError("Assertion expired.", "expired_assertion")
    expires_at = timezone.now() + timedelta(seconds=settings.DEVICE_ASSERTION_TTL_SECONDS + 120)
    _, created = DeviceAssertionJti.objects.get_or_create(
        jti=str(jti)[:64],
        defaults={"device": device, "expires_at": expires_at},
    )
    if not created:
        raise DeviceAuthError("Assertion replay detected.", "replay")
    return claims
