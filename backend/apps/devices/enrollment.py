from __future__ import annotations

import uuid

from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_audit
from apps.devices.crypto import DeviceAuthError, issue_device_access_token, verify_client_assertion
from apps.devices.models import (
    ConnectivityStatus,
    CredentialStatus,
    Device,
    DeviceCredential,
    DeviceStatus,
    EnrollmentSession,
    ManagementMode,
)
from apps.devices.services import EnrollmentError, _reject_if_unusable
from apps.devices.tokens import secrets_match


ALLOWED_PUBLIC_KEY_PREFIX = "-----BEGIN PUBLIC KEY-----"
ALLOWED_PUBLIC_KEY_SUFFIX = "-----END PUBLIC KEY-----"


def _validate_public_key_pem(pem: str) -> str:
    text = (pem or "").strip().replace("\r\n", "\n")
    if not text.startswith(ALLOWED_PUBLIC_KEY_PREFIX) or not text.endswith(ALLOWED_PUBLIC_KEY_SUFFIX):
        raise EnrollmentError("public_key must be a PEM-encoded SubjectPublicKeyInfo.", "invalid_key")
    if "PRIVATE" in text.upper():
        raise EnrollmentError("Private keys are not accepted.", "invalid_key")
    from apps.devices.crypto import load_ec_public_key

    try:
        load_ec_public_key(text)
    except Exception as exc:  # noqa: BLE001
        raise EnrollmentError("public_key is not a valid EC public key.", "invalid_key") from exc
    return text


@transaction.atomic
def enroll_android_device(
    *,
    session_id,
    raw_secret: str,
    public_key_id: str,
    public_key_pem: str,
    disclosure_accepted: bool,
    management_mode: str,
    display_name: str = "",
    manufacturer: str = "",
    model: str = "",
    android_version: str | None = None,
    dpc_version: str | None = None,
    request_meta: dict | None = None,
) -> tuple[Device, DeviceCredential, str, int]:
    meta = request_meta or {}
    if not disclosure_accepted:
        raise EnrollmentError("Management disclosure must be accepted.", "disclosure_required")
    try:
        session_uuid = uuid.UUID(str(session_id))
    except (ValueError, TypeError) as exc:
        raise EnrollmentError("Enrollment session not found.", "not_found") from exc
    public_key_id = (public_key_id or "").strip()
    if not public_key_id or len(public_key_id) > 128:
        raise EnrollmentError("public_key_id is required.", "invalid_key")
    pem = _validate_public_key_pem(public_key_pem)
    if management_mode not in ManagementMode.values:
        raise EnrollmentError("Invalid management mode.", "invalid_mode")

    session = (
        EnrollmentSession.objects.select_for_update()
        .select_related("organization")
        .filter(pk=session_uuid)
        .first()
    )
    if session is None:
        raise EnrollmentError("Enrollment session not found.", "not_found")
    _reject_if_unusable(session)
    if not secrets_match(raw_secret, session.token_hash):
        raise EnrollmentError("Invalid enrollment secret.", "invalid_secret")
    allowed = set(session.allowed_provisioning_modes or [])
    if management_mode not in allowed:
        raise EnrollmentError("Provisioning mode is not allowed for this session.", "invalid_mode")

    session.status = "consumed"
    session.used_at = timezone.now()
    session.save(update_fields=["status", "used_at"])

    name = (display_name or "").strip() or f"{manufacturer} {model}".strip() or "Android device"
    device = Device.objects.create(
        organization=session.organization,
        display_name=name[:120],
        manufacturer=(manufacturer or "")[:120],
        model=(model or "")[:120],
        android_version=android_version,
        dpc_version=dpc_version,
        management_mode=management_mode,
        enrolled_at=timezone.now(),
        is_active=True,
    )
    credential = DeviceCredential.objects.create(
        device=device,
        public_key_id=public_key_id,
        public_key=pem,
        status=CredentialStatus.ACTIVE,
        issued_at=timezone.now(),
    )
    access_token, ttl = issue_device_access_token(device=device, credential=credential)
    record_audit(
        organization=session.organization,
        actor_device=device,
        target_device=device,
        action="enrollment.device_succeeded",
        result="success",
        new_snapshot={
            "enrollment_session_id": str(session.id),
            "device_id": str(device.id),
            "public_key_id": public_key_id,
            "management_mode": management_mode,
        },
        **meta,
    )
    return device, credential, access_token, ttl


@transaction.atomic
def issue_token_for_assertion(*, device_id, public_key_id: str, client_assertion: str) -> tuple[Device, DeviceCredential, str, int]:
    try:
        device_uuid = uuid.UUID(str(device_id))
    except (ValueError, TypeError) as exc:
        raise DeviceAuthError("Device is unknown or revoked.", "revoked") from exc
    device = Device.objects.select_for_update().select_related("organization").filter(pk=device_uuid).first()
    if device is None or not device.is_active:
        raise DeviceAuthError("Device is unknown or revoked.", "revoked")
    credential = device.credentials.select_for_update().filter(
        public_key_id=public_key_id,
        status=CredentialStatus.ACTIVE,
    ).first()
    if credential is None:
        raise DeviceAuthError("Device credential is revoked or rotated.", "revoked")
    verify_client_assertion(device=device, credential=credential, assertion=client_assertion)
    credential.last_used_at = timezone.now()
    credential.save(update_fields=["last_used_at"])
    token, ttl = issue_device_access_token(device=device, credential=credential)
    return device, credential, token, ttl


@transaction.atomic
def record_heartbeat(
    *,
    device: Device,
    app_version: str | None,
    android_version: str | None,
    manufacturer: str | None,
    model: str | None,
    management_active: bool,
    management_mode: str | None,
    connectivity: str | None,
    battery_level: int | None,
    dpc_version: str | None,
    dns_filter_state: str | None = None,
    dns_filter_error: str | None = None,
) -> Device:
    device = Device.objects.select_for_update().get(pk=device.pk)
    if not device.is_active:
        raise DeviceAuthError("Device is revoked.", "revoked")
    if manufacturer:
        device.manufacturer = manufacturer[:120]
    if model:
        device.model = model[:120]
    if android_version:
        device.android_version = android_version[:32]
    if dpc_version:
        device.dpc_version = dpc_version[:32]
    if management_mode in ManagementMode.values:
        device.management_mode = management_mode
    device.save()
    status = device.status
    status.last_seen_at = timezone.now()
    status.app_version = (app_version or dpc_version or status.app_version)
    status.management_active = bool(management_active)
    if connectivity in ConnectivityStatus.values:
        status.connectivity = connectivity
    else:
        status.connectivity = ConnectivityStatus.ONLINE
    if battery_level is not None:
        status.battery_level = max(0, min(100, int(battery_level)))
    if dns_filter_state in DeviceStatus.DnsFilterReportedState.values:
        status.dns_filter_state = dns_filter_state
        if dns_filter_state in (
            DeviceStatus.DnsFilterReportedState.RUNNING,
            DeviceStatus.DnsFilterReportedState.STOPPED,
            DeviceStatus.DnsFilterReportedState.UNKNOWN,
        ):
            status.dns_filter_error = None
        elif dns_filter_error:
            status.dns_filter_error = str(dns_filter_error)[:64]
        elif dns_filter_state == DeviceStatus.DnsFilterReportedState.CONSENT_REQUIRED:
            status.dns_filter_error = "vpn_consent_required"
    status.save()
    return device
