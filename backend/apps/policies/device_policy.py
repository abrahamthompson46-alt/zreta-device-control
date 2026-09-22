from __future__ import annotations

import uuid
from typing import Any

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.audit.services import record_audit
from apps.devices.models import DeviceStatus
from apps.policies.assignments import resolve_effective_version
from apps.policies.exceptions import PolicyError
from apps.policies.models import DevicePolicyAssignment, PolicyVersion, PolicyVersionStatus
from apps.policies.schema import validate_policy_document

APPLIED_RESULTS = frozenset({"applied", "cached_unchanged"})
# Telemetry-only ACK results (do not update applied_policy_version*).
REJECTED_RESULTS = frozenset(
    {
        "rejected_malformed",
        "rejected_schema",
        "enforcement_partial",
        "rejected_enforcement",
    }
)
ALLOWED_RESULTS = APPLIED_RESULTS | REJECTED_RESULTS


def get_device_effective_policy(*, device) -> dict[str, Any]:
    """Return the effective policy payload for an authenticated device (no client device_id)."""
    assignment = (
        DevicePolicyAssignment.objects.filter(device_id=device.id, organization_id=device.organization_id)
        .select_related("policy", "pinned_version")
        .first()
    )
    if assignment is None:
        return {
            "assignment_state": "unassigned",
            "policy_id": None,
            "policy_version_id": None,
            "version_number": None,
            "schema_version": None,
            "content_hash": None,
            "published_at": None,
            "document": None,
            "etag": None,
        }

    version = resolve_effective_version(assignment)
    if version is None:
        return {
            "assignment_state": "assigned",
            "policy_id": str(assignment.policy_id),
            "policy_version_id": None,
            "version_number": None,
            "schema_version": None,
            "content_hash": None,
            "published_at": None,
            "document": None,
            "etag": None,
            "reason": "no_published_version",
        }

    etag = f'W/"{version.id}"'
    return {
        "assignment_state": "assigned",
        "policy_id": str(assignment.policy_id),
        "policy_version_id": str(version.id),
        "version_number": version.version_number,
        "schema_version": version.schema_version,
        "content_hash": version.content_hash,
        "published_at": version.published_at,
        "document": version.document,
        "etag": etag,
    }


def _parse_applied_at(applied_at):
    if not applied_at:
        return timezone.now()
    parsed = parse_datetime(str(applied_at))
    if parsed is not None and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.utc)
    return parsed or timezone.now()


@transaction.atomic
def acknowledge_device_policy(
    *,
    device,
    policy_version_id,
    version_number: int | None,
    content_hash: str | None,
    applied_at,
    result: str,
    client_event_id,
    request_meta: dict | None = None,
) -> dict[str, Any]:
    """Record device policy ACK telemetry. Only effective published versions may mark applied."""
    if not device.is_active:
        raise PolicyError("Device is revoked.", "revoked")

    try:
        event_uuid = uuid.UUID(str(client_event_id))
    except (ValueError, TypeError) as exc:
        raise PolicyError("client_event_id must be a UUID.", "invalid_event_id") from exc

    if result not in ALLOWED_RESULTS:
        raise PolicyError("Invalid acknowledgement result.", "invalid_result")

    # Lock status row only (no nullable outer joins under FOR UPDATE).
    status = DeviceStatus.objects.select_for_update().get(device_id=device.id)
    if status.policy_ack_client_event_id == event_uuid:
        return {
            "accepted": True,
            "idempotent": True,
            "applied_updated": False,
            "applied_policy_version": status.applied_policy_version,
            "applied_policy_version_id": str(status.applied_policy_version_ref_id)
            if status.applied_policy_version_ref_id
            else None,
        }

    assignment = (
        DevicePolicyAssignment.objects.select_for_update()
        .filter(device_id=device.id, organization_id=device.organization_id)
        .first()
    )
    if assignment is None:
        raise PolicyError("Device has no policy assignment.", "not_assigned")

    effective = resolve_effective_version(assignment)

    version = (
        PolicyVersion.objects.filter(
            pk=policy_version_id,
            organization_id=device.organization_id,
            policy_id=assignment.policy_id,
        ).first()
    )
    if version is None:
        raise PolicyError("Policy version not found for this assignment.", "version_not_found")

    if version_number is not None and int(version_number) != version.version_number:
        raise PolicyError("version_number does not match server version.", "version_mismatch")
    if content_hash and version.content_hash and content_hash != version.content_hash:
        raise PolicyError("content_hash does not match server version.", "hash_mismatch")

    meta = request_meta or {}
    applied_updated = False
    ack_result = result

    if result in APPLIED_RESULTS:
        if version.status != PolicyVersionStatus.PUBLISHED:
            # Draft/superseded/archived cannot be recorded as applied.
            ack_result = "stale_version"
            status.policy_ack_result = ack_result
            status.policy_ack_client_event_id = event_uuid
            status.policy_last_error = ack_result
            status.save(
                update_fields=[
                    "policy_ack_result",
                    "policy_ack_client_event_id",
                    "policy_last_error",
                    "updated_at",
                ]
            )
        elif effective is None or effective.id != version.id:
            ack_result = "stale_version"
            status.policy_ack_result = ack_result
            status.policy_ack_client_event_id = event_uuid
            status.policy_last_error = ack_result
            status.save(
                update_fields=[
                    "policy_ack_result",
                    "policy_ack_client_event_id",
                    "policy_last_error",
                    "updated_at",
                ]
            )
        else:
            validate_policy_document(version.document)
            status.applied_policy_version = version.version_number
            status.applied_policy_version_ref = version
            status.policy_applied_at = _parse_applied_at(applied_at)
            status.policy_ack_result = result[:32]
            status.policy_ack_client_event_id = event_uuid
            status.policy_last_error = None
            status.save(
                update_fields=[
                    "applied_policy_version",
                    "applied_policy_version_ref",
                    "policy_applied_at",
                    "policy_ack_result",
                    "policy_ack_client_event_id",
                    "policy_last_error",
                    "updated_at",
                ]
            )
            applied_updated = True
    else:
        # Rejected results: telemetry only — never claim the version was applied.
        status.policy_ack_result = result[:32]
        status.policy_ack_client_event_id = event_uuid
        status.policy_last_error = result[:32]
        status.save(
            update_fields=[
                "policy_ack_result",
                "policy_ack_client_event_id",
                "policy_last_error",
                "updated_at",
            ]
        )

    record_audit(
        organization=device.organization,
        actor_device=device,
        target_device=device,
        action="policy.ack",
        result="success" if applied_updated else "failure",
        new_snapshot={
            "device_id": str(device.id),
            "policy_id": str(assignment.policy_id),
            "version_id": str(version.id),
            "version_number": version.version_number,
            "content_hash": version.content_hash,
            "ack_result": ack_result,
            "applied_updated": applied_updated,
            "client_event_id": str(event_uuid),
        },
        **meta,
    )
    return {
        "accepted": True,
        "idempotent": False,
        "applied_updated": applied_updated,
        "ack_result": ack_result,
        "applied_policy_version": status.applied_policy_version,
        "applied_policy_version_id": str(status.applied_policy_version_ref_id)
        if status.applied_policy_version_ref_id
        else None,
    }
