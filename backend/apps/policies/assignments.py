from __future__ import annotations

from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.services import record_audit
from apps.devices.models import Device
from apps.policies.exceptions import PolicyError
from apps.policies.lifecycle import create_draft_version
from apps.policies.models import DevicePolicyAssignment, Policy, PolicyVersion, PolicyVersionStatus
from apps.policies.schema import empty_policy_document


def _assignment_snapshot(assignment: DevicePolicyAssignment) -> dict[str, Any]:
    return {
        "assignment_id": str(assignment.id),
        "device_id": str(assignment.device_id),
        "policy_id": str(assignment.policy_id),
        "pinned_version_id": str(assignment.pinned_version_id) if assignment.pinned_version_id else None,
    }


@transaction.atomic
def create_policy(
    *,
    organization,
    name: str,
    description: str = "",
    actor_user=None,
    request_meta: dict | None = None,
) -> tuple[Policy, PolicyVersion]:
    """Create a Policy and its initial empty draft via the lifecycle service."""
    name = (name or "").strip()
    if not name:
        raise PolicyError("Policy name is required.", "invalid_name")
    try:
        policy = Policy(
            organization=organization,
            name=name,
            description=description or "",
            created_by=actor_user,
        )
        policy.save()
    except IntegrityError as exc:
        raise PolicyError("An active policy with this name already exists.", "duplicate_name") from exc

    meta = request_meta or {}
    record_audit(
        organization=organization,
        actor_user=actor_user,
        action="policy.created",
        result="success",
        new_snapshot={
            "policy_id": str(policy.id),
            "name": policy.name,
        },
        **meta,
    )
    version = create_draft_version(
        organization=organization,
        policy_id=policy.id,
        actor_user=actor_user,
        document=empty_policy_document(),
        request_meta=meta,
    )
    return policy, version


@transaction.atomic
def update_policy_metadata(
    *,
    organization,
    policy_id,
    name: str | None = None,
    description: str | None = None,
    archived: bool | None = None,
    actor_user=None,
    request_meta: dict | None = None,
) -> Policy:
    policy = (
        Policy.objects.select_for_update()
        .filter(pk=policy_id, organization_id=organization.id)
        .first()
    )
    if policy is None:
        raise PolicyError("Policy not found in this organization.", "policy_not_found")

    old = {"name": policy.name, "archived_at": policy.archived_at.isoformat() if policy.archived_at else None}
    if name is not None:
        cleaned = name.strip()
        if not cleaned:
            raise PolicyError("Policy name is required.", "invalid_name")
        policy.name = cleaned
    if description is not None:
        policy.description = description
    if archived is True and policy.archived_at is None:
        policy.archived_at = timezone.now()
    elif archived is False:
        policy.archived_at = None
    try:
        policy.save()
    except IntegrityError as exc:
        raise PolicyError("An active policy with this name already exists.", "duplicate_name") from exc

    meta = request_meta or {}
    record_audit(
        organization=organization,
        actor_user=actor_user,
        action="policy.updated",
        result="success",
        old_snapshot=old,
        new_snapshot={
            "policy_id": str(policy.id),
            "name": policy.name,
            "archived_at": policy.archived_at.isoformat() if policy.archived_at else None,
        },
        **meta,
    )
    return policy


def resolve_effective_version(assignment: DevicePolicyAssignment) -> PolicyVersion | None:
    """Pinned published version if set; otherwise current published version of the policy."""
    if assignment.pinned_version_id:
        pinned = assignment.pinned_version
        if pinned.status == PolicyVersionStatus.PUBLISHED:
            return pinned
        return None
    return (
        PolicyVersion.objects.filter(
            policy_id=assignment.policy_id,
            status=PolicyVersionStatus.PUBLISHED,
        )
        .order_by("-version_number")
        .first()
    )


def _resolve_pinned(*, organization, policy: Policy, pinned_version_id) -> PolicyVersion | None:
    if pinned_version_id is None:
        return None
    pinned = (
        PolicyVersion.objects.filter(
            pk=pinned_version_id,
            organization_id=organization.id,
            policy_id=policy.id,
        ).first()
    )
    if pinned is None:
        raise PolicyError("Pinned version not found for this policy.", "version_not_found")
    if pinned.status != PolicyVersionStatus.PUBLISHED:
        raise PolicyError("Pinned version must be published.", "pinned_not_published")
    return pinned


@transaction.atomic
def assign_policy_to_device(
    *,
    organization,
    device_id,
    policy_id,
    pinned_version_id=None,
    actor_user=None,
    request_meta: dict | None = None,
) -> DevicePolicyAssignment:
    device = Device.objects.select_for_update().filter(pk=device_id, organization_id=organization.id).first()
    if device is None:
        raise PolicyError("Device not found in this organization.", "device_not_found")
    policy = Policy.objects.filter(pk=policy_id, organization_id=organization.id).first()
    if policy is None:
        raise PolicyError("Policy not found in this organization.", "policy_not_found")
    if DevicePolicyAssignment.objects.filter(device_id=device.id).exists():
        raise PolicyError("Device already has a policy assignment.", "assignment_exists")

    pinned = _resolve_pinned(organization=organization, policy=policy, pinned_version_id=pinned_version_id)
    assignment = DevicePolicyAssignment(
        organization=organization,
        device=device,
        policy=policy,
        pinned_version=pinned,
        assigned_by=actor_user,
    )
    try:
        assignment.save()
    except IntegrityError as exc:
        raise PolicyError("Device already has a policy assignment.", "assignment_exists") from exc

    meta = request_meta or {}
    record_audit(
        organization=organization,
        actor_user=actor_user,
        target_device=device,
        action="policy.assigned",
        result="success",
        new_snapshot=_assignment_snapshot(assignment),
        **meta,
    )
    return assignment


@transaction.atomic
def update_device_policy_assignment(
    *,
    organization,
    assignment_id,
    policy_id=None,
    pinned_version_id=...,
    actor_user=None,
    request_meta: dict | None = None,
) -> DevicePolicyAssignment:
    assignment = (
        DevicePolicyAssignment.objects.select_for_update()
        .filter(pk=assignment_id, organization_id=organization.id)
        .first()
    )
    if assignment is None:
        raise PolicyError("Assignment not found in this organization.", "assignment_not_found")

    old = _assignment_snapshot(assignment)
    policy = assignment.policy
    if policy_id is not None:
        policy = Policy.objects.filter(pk=policy_id, organization_id=organization.id).first()
        if policy is None:
            raise PolicyError("Policy not found in this organization.", "policy_not_found")
        assignment.policy = policy

    if pinned_version_id is not ...:
        assignment.pinned_version = _resolve_pinned(
            organization=organization,
            policy=policy,
            pinned_version_id=pinned_version_id,
        )

    assignment.save()
    meta = request_meta or {}
    record_audit(
        organization=organization,
        actor_user=actor_user,
        target_device=assignment.device,
        action="policy.assigned",
        result="success",
        old_snapshot=old,
        new_snapshot=_assignment_snapshot(assignment),
        **meta,
    )
    return assignment


@transaction.atomic
def unassign_device_policy(
    *,
    organization,
    assignment_id,
    actor_user=None,
    request_meta: dict | None = None,
) -> None:
    assignment = (
        DevicePolicyAssignment.objects.select_for_update()
        .filter(pk=assignment_id, organization_id=organization.id)
        .first()
    )
    if assignment is None:
        raise PolicyError("Assignment not found in this organization.", "assignment_not_found")
    snapshot = _assignment_snapshot(assignment)
    device = assignment.device
    assignment.delete()
    meta = request_meta or {}
    record_audit(
        organization=organization,
        actor_user=actor_user,
        target_device=device,
        action="policy.unassigned",
        result="success",
        old_snapshot=snapshot,
        **meta,
    )
