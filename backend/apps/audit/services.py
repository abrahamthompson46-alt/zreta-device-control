from __future__ import annotations

from typing import Any

from django.http import HttpRequest

from .models import AuditEvent

SENSITIVE_KEYS = {
    "password",
    "password1",
    "password2",
    "old_password",
    "new_password",
    "token",
    "secret",
    "enrollment_secret",
    "raw_secret",
    "private_key",
    "access_token",
    "refresh_token",
    "client_assertion",
    "authorization",
    "csrfmiddlewaretoken",
    "latitude",
    "longitude",
    "lat",
    "lon",
    "token_hash",
}


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, inner in value.items():
            if str(key).lower() in SENSITIVE_KEYS or any(
                part in str(key).lower() for part in ("secret", "token", "password", "private")
            ):
                redacted[key] = "[redacted]"
            else:
                redacted[key] = _redact(inner)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def client_ip(request: HttpRequest | None) -> str | None:
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()[:45]
    return request.META.get("REMOTE_ADDR")


def request_meta(request: HttpRequest | None) -> dict[str, Any]:
    if request is None:
        return {}
    return {
        "ip_address": client_ip(request),
        "user_agent": (request.META.get("HTTP_USER_AGENT") or "")[:500] or None,
        "request_id": request.headers.get("X-Request-ID") if hasattr(request, "headers") else None,
    }


def record_audit(
    *,
    organization,
    action: str,
    result: str = "success",
    actor_user=None,
    actor_device=None,
    target_device=None,
    old_snapshot=None,
    new_snapshot=None,
    request_id=None,
    ip_address=None,
    user_agent=None,
) -> AuditEvent:
    return AuditEvent.objects.create(
        organization=organization,
        actor_user=actor_user,
        actor_device=actor_device,
        target_device=target_device,
        action=action,
        result=result,
        request_id=request_id,
        ip_address=ip_address,
        user_agent=user_agent,
        old_snapshot=_redact(old_snapshot) if old_snapshot is not None else None,
        new_snapshot=_redact(new_snapshot) if new_snapshot is not None else None,
    )
