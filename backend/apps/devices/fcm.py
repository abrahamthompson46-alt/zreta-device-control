"""FCM wake helpers. Not an authoritative command channel — devices still pull policy via API."""

from __future__ import annotations

import json
import logging
from typing import Iterable

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

WAKE_DATA_TYPE = "policy_wake"


def _firebase_ready() -> bool:
    creds = getattr(settings, "FIREBASE_CREDENTIALS_JSON", None) or ""
    path = getattr(settings, "FIREBASE_CREDENTIALS_FILE", None) or ""
    return bool(str(creds).strip() or str(path).strip())


def _ensure_app():
    import firebase_admin
    from firebase_admin import credentials

    if firebase_admin._apps:
        return firebase_admin.get_app()
    raw = getattr(settings, "FIREBASE_CREDENTIALS_JSON", None) or ""
    path = getattr(settings, "FIREBASE_CREDENTIALS_FILE", None) or ""
    if str(raw).strip():
        info = json.loads(raw)
        cred = credentials.Certificate(info)
    elif str(path).strip():
        cred = credentials.Certificate(str(path).strip())
    else:
        raise RuntimeError("firebase_not_configured")
    return firebase_admin.initialize_app(cred)


def register_fcm_token(*, device, token: str) -> None:
    text = (token or "").strip()
    if not text or len(text) > 512:
        raise ValueError("invalid_fcm_token")
    device.fcm_registration_token = text
    device.fcm_token_updated_at = timezone.now()
    device.save(update_fields=["fcm_registration_token", "fcm_token_updated_at", "updated_at"])


def clear_fcm_token(*, device) -> None:
    if not device.fcm_registration_token:
        return
    device.fcm_registration_token = None
    device.fcm_token_updated_at = timezone.now()
    device.save(update_fields=["fcm_registration_token", "fcm_token_updated_at", "updated_at"])


def send_policy_wake(*, tokens: Iterable[str], reason: str = "policy_changed") -> dict:
    """
    Send data-only FCM wakes. Returns counts; never raises to callers of publish path.
    """
    unique = []
    seen = set()
    for token in tokens:
        t = (token or "").strip()
        if not t or t in seen:
            continue
        seen.add(t)
        unique.append(t)
    if not unique:
        return {"attempted": 0, "sent": 0, "failed": 0, "skipped": "no_tokens"}
    if not _firebase_ready():
        logger.info("FCM wake skipped: Firebase credentials not configured (%s)", reason)
        return {"attempted": len(unique), "sent": 0, "failed": 0, "skipped": "firebase_not_configured"}

    try:
        _ensure_app()
        from firebase_admin import messaging
    except Exception as exc:  # pragma: no cover - env dependent
        logger.warning("FCM init failed: %s", type(exc).__name__)
        return {"attempted": len(unique), "sent": 0, "failed": len(unique), "skipped": "init_failed"}

    sent = 0
    failed = 0
    for token in unique:
        message = messaging.Message(
            data={"type": WAKE_DATA_TYPE, "reason": reason[:64]},
            token=token,
            android=messaging.AndroidConfig(priority="high"),
        )
        try:
            messaging.send(message)
            sent += 1
        except Exception as exc:  # pragma: no cover
            failed += 1
            logger.info("FCM send failed: %s", type(exc).__name__)
    return {"attempted": len(unique), "sent": sent, "failed": failed, "skipped": None}


def wake_devices_for_policy(*, organization_id, policy_id, reason: str = "policy_changed") -> dict:
    from apps.devices.models import Device
    from apps.policies.models import DevicePolicyAssignment

    device_ids = DevicePolicyAssignment.objects.filter(
        organization_id=organization_id,
        policy_id=policy_id,
    ).values_list("device_id", flat=True)
    tokens = (
        Device.objects.filter(
            id__in=device_ids,
            organization_id=organization_id,
            is_active=True,
        )
        .exclude(fcm_registration_token__isnull=True)
        .exclude(fcm_registration_token="")
        .values_list("fcm_registration_token", flat=True)
    )
    return send_policy_wake(tokens=tokens, reason=reason)
