from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import json

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_audit
from apps.devices.models import (
    CredentialStatus,
    Device,
    EnrollmentSession,
    EnrollmentStatus,
    ProvisioningMode,
)
from apps.devices.tokens import generate_enrollment_secret, hash_enrollment_secret, secrets_match


class EnrollmentError(Exception):
    def __init__(self, message: str, code: str = "invalid"):
        super().__init__(message)
        self.code = code


@dataclass
class CreatedEnrollment:
    session: EnrollmentSession
    raw_secret: str
    payload: dict


def build_enrollment_payload(session: EnrollmentSession, raw_secret: str) -> dict:
    return {
        "v": 1,
        "api_base": settings.PUBLIC_API_BASE_URL,
        "enrollment_session_id": str(session.id),
        "enrollment_secret": raw_secret,
    }


def canonical_enrollment_payload_json(payload: dict) -> str:
    """
    Compact JSON bytes encoded into the enrollment QR and shown for paste.
    Must stay byte-identical for QR and dashboard copy/paste fallback.
    """
    required = ("v", "api_base", "enrollment_session_id", "enrollment_secret")
    missing = [key for key in required if key not in payload]
    if missing:
        raise EnrollmentError(f"Incomplete enrollment payload: {', '.join(missing)}", "invalid_payload")
    ordered = {key: payload[key] for key in required}
    return json.dumps(ordered, separators=(",", ":"), ensure_ascii=True)


@transaction.atomic
def create_enrollment_session(
    *,
    organization,
    created_by,
    allowed_provisioning_modes: list[str] | None = None,
    request_meta: dict | None = None,
) -> CreatedEnrollment:
    modes = list(allowed_provisioning_modes or [ProvisioningMode.DEVICE_OWNER])
    valid = {choice.value for choice in ProvisioningMode}
    if not modes or any(mode not in valid for mode in modes):
        raise EnrollmentError("Invalid provisioning mode.", "invalid_mode")
    raw_secret = generate_enrollment_secret()
    session = EnrollmentSession.objects.create(
        organization=organization,
        created_by=created_by,
        token_hash=hash_enrollment_secret(raw_secret),
        expires_at=timezone.now() + timedelta(minutes=settings.ENROLLMENT_SESSION_TTL_MINUTES),
        status=EnrollmentStatus.PENDING,
        allowed_provisioning_modes=modes,
    )
    meta = request_meta or {}
    record_audit(
        organization=organization,
        actor_user=created_by,
        action="enrollment.created",
        result="success",
        new_snapshot={
            "enrollment_session_id": str(session.id),
            "expires_at": session.expires_at.isoformat(),
            "allowed_provisioning_modes": modes,
        },
        **meta,
    )
    return CreatedEnrollment(
        session=session,
        raw_secret=raw_secret,
        payload=build_enrollment_payload(session, raw_secret),
    )


@transaction.atomic
def cancel_enrollment_session(*, session: EnrollmentSession, actor_user, request_meta: dict | None = None) -> EnrollmentSession:
    session = EnrollmentSession.objects.select_for_update().get(pk=session.pk)
    if session.status != EnrollmentStatus.PENDING:
        raise EnrollmentError("Only pending enrollment sessions can be cancelled.", "not_pending")
    session.status = EnrollmentStatus.CANCELLED
    session.cancelled_at = timezone.now()
    session.save(update_fields=["status", "cancelled_at"])
    record_audit(
        organization=session.organization,
        actor_user=actor_user,
        action="enrollment.cancelled",
        result="success",
        new_snapshot={"enrollment_session_id": str(session.id)},
        **(request_meta or {}),
    )
    return session


def _reject_if_unusable(session: EnrollmentSession) -> None:
    now = timezone.now()
    if session.status == EnrollmentStatus.CANCELLED or session.cancelled_at:
        raise EnrollmentError("Enrollment session was cancelled.", "cancelled")
    if session.status == EnrollmentStatus.CONSUMED or session.used_at:
        raise EnrollmentError("Enrollment session was already used.", "used")
    if session.status == EnrollmentStatus.EXPIRED or session.expires_at <= now:
        if session.status == EnrollmentStatus.PENDING:
            session.status = EnrollmentStatus.EXPIRED
            session.save(update_fields=["status"])
        raise EnrollmentError("Enrollment session has expired.", "expired")
    if session.status != EnrollmentStatus.PENDING:
        raise EnrollmentError("Enrollment session is not pending.", "invalid")


@transaction.atomic
def consume_enrollment_session(*, session_id, raw_secret: str, organization=None) -> EnrollmentSession:
    """Atomically consume a single-use enrollment secret. Used by tests now; Phase 2 device enroll will call this."""
    session = (
        EnrollmentSession.objects.select_for_update()
        .select_related("organization")
        .filter(pk=session_id)
        .first()
    )
    if session is None:
        raise EnrollmentError("Enrollment session not found.", "not_found")
    if organization is not None and session.organization_id != organization.id:
        raise EnrollmentError("Enrollment session does not belong to this organization.", "wrong_org")
    _reject_if_unusable(session)
    if not secrets_match(raw_secret, session.token_hash):
        raise EnrollmentError("Invalid enrollment secret.", "invalid_secret")
    session.status = EnrollmentStatus.CONSUMED
    session.used_at = timezone.now()
    session.save(update_fields=["status", "used_at"])
    return session


@transaction.atomic
def revoke_device(*, device: Device, actor_user, request_meta: dict | None = None) -> Device:
    device = Device.objects.select_for_update().select_related("organization").get(pk=device.pk)
    if not device.is_active:
        raise EnrollmentError("Device is already revoked.", "already_revoked")
    old = {"is_active": True}
    device.is_active = False
    device.fcm_registration_token = None
    device.fcm_token_updated_at = timezone.now()
    device.save(update_fields=["is_active", "fcm_registration_token", "fcm_token_updated_at", "updated_at"])
    device.credentials.filter(status=CredentialStatus.ACTIVE).update(
        status=CredentialStatus.REVOKED,
        revoked_at=timezone.now(),
    )
    record_audit(
        organization=device.organization,
        actor_user=actor_user,
        target_device=device,
        action="device.revoked",
        result="success",
        old_snapshot=old,
        new_snapshot={"is_active": False},
        **(request_meta or {}),
    )
    return device


@transaction.atomic
def rename_device(*, device: Device, display_name: str, actor_user, request_meta: dict | None = None) -> Device:
    device = Device.objects.select_for_update().select_related("organization").get(pk=device.pk)
    if not device.is_active:
        raise EnrollmentError("Revoked devices cannot be managed.", "revoked")
    old_name = device.display_name
    device.display_name = display_name
    device.save(update_fields=["display_name", "updated_at"])
    record_audit(
        organization=device.organization,
        actor_user=actor_user,
        target_device=device,
        action="device.renamed",
        result="success",
        old_snapshot={"display_name": old_name},
        new_snapshot={"display_name": display_name},
        **(request_meta or {}),
    )
    return device
