"""PolicySchedule: publish a draft at activate_at (UTC). FCM wake follows publish."""

from __future__ import annotations

from datetime import datetime

from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_audit
from apps.policies.exceptions import PolicyError
from apps.policies.lifecycle import publish_version
from apps.policies.models import (
    Policy,
    PolicySchedule,
    PolicyScheduleStatus,
    PolicyVersion,
    PolicyVersionStatus,
)


def schedule_policy_publish(
    *,
    organization,
    policy_id,
    version_id,
    activate_at: datetime,
    actor_user=None,
    request_meta: dict | None = None,
) -> PolicySchedule:
    """Create a pending schedule to publish a draft version at activate_at."""
    if activate_at is None:
        raise PolicyError("activate_at is required.", "invalid_activate_at")
    if timezone.is_naive(activate_at):
        raise PolicyError("activate_at must be timezone-aware (UTC).", "invalid_activate_at")
    if activate_at <= timezone.now():
        raise PolicyError("activate_at must be in the future.", "activate_at_not_future")

    policy = Policy.objects.filter(pk=policy_id, organization_id=organization.id).first()
    if policy is None:
        raise PolicyError("Policy not found.", "policy_not_found")

    version = (
        PolicyVersion.objects.filter(
            pk=version_id,
            policy_id=policy.id,
            organization_id=organization.id,
        )
        .first()
    )
    if version is None:
        raise PolicyError("Policy version not found.", "version_not_found")
    if version.status != PolicyVersionStatus.DRAFT:
        raise PolicyError("Only draft versions can be scheduled for publish.", "not_draft")

    # One pending schedule per version.
    existing = PolicySchedule.objects.filter(
        version_id=version.id,
        status=PolicyScheduleStatus.PENDING,
    ).first()
    if existing is not None:
        raise PolicyError("A pending schedule already exists for this version.", "schedule_exists")

    schedule = PolicySchedule.objects.create(
        organization=organization,
        policy=policy,
        version=version,
        activate_at=activate_at,
        status=PolicyScheduleStatus.PENDING,
        created_by=actor_user,
    )
    meta = request_meta or {}
    record_audit(
        organization=organization,
        actor_user=actor_user,
        action="policy.schedule_created",
        result="success",
        new_snapshot={
            "schedule_id": str(schedule.id),
            "policy_id": str(policy.id),
            "version_id": str(version.id),
            "activate_at": schedule.activate_at.isoformat(),
        },
        **meta,
    )
    return schedule


def cancel_policy_schedule(
    *,
    organization,
    schedule_id,
    actor_user=None,
    request_meta: dict | None = None,
) -> PolicySchedule:
    schedule = (
        PolicySchedule.objects.filter(pk=schedule_id, organization_id=organization.id)
        .select_related("policy", "version")
        .first()
    )
    if schedule is None:
        raise PolicyError("Schedule not found.", "schedule_not_found")
    if schedule.status != PolicyScheduleStatus.PENDING:
        raise PolicyError("Only pending schedules can be cancelled.", "schedule_not_pending")

    schedule.status = PolicyScheduleStatus.CANCELLED
    schedule.completed_at = timezone.now()
    schedule.save(update_fields=["status", "completed_at"])
    meta = request_meta or {}
    record_audit(
        organization=organization,
        actor_user=actor_user,
        action="policy.schedule_cancelled",
        result="success",
        new_snapshot={"schedule_id": str(schedule.id)},
        **meta,
    )
    return schedule


def process_due_schedules(*, now=None, limit: int = 50) -> dict:
    """
    Publish due pending schedules. Safe to run from cron/management command.
    Returns counts; individual publish failures mark the schedule failed.
    """
    cutoff = now or timezone.now()
    due_ids = list(
        PolicySchedule.objects.filter(
            status=PolicyScheduleStatus.PENDING,
            activate_at__lte=cutoff,
        )
        .order_by("activate_at")
        .values_list("id", flat=True)[:limit]
    )
    completed = 0
    failed = 0
    for schedule_id in due_ids:
        ok = _process_one_schedule(schedule_id)
        if ok:
            completed += 1
        else:
            failed += 1
    return {"due": len(due_ids), "completed": completed, "failed": failed}


@transaction.atomic
def _process_one_schedule(schedule_id) -> bool:
    schedule = (
        PolicySchedule.objects.select_for_update()
        .select_related("organization", "version", "policy")
        .filter(pk=schedule_id)
        .first()
    )
    if schedule is None or schedule.status != PolicyScheduleStatus.PENDING:
        return False
    if schedule.activate_at > timezone.now():
        return False

    try:
        publish_version(
            organization=schedule.organization,
            version_id=schedule.version_id,
            actor_user=schedule.created_by,
        )
    except PolicyError as exc:
        schedule.status = PolicyScheduleStatus.FAILED
        schedule.completed_at = timezone.now()
        schedule.last_error = (exc.code or "publish_failed")[:64]
        schedule.save(update_fields=["status", "completed_at", "last_error"])
        return False
    except Exception:
        schedule.status = PolicyScheduleStatus.FAILED
        schedule.completed_at = timezone.now()
        schedule.last_error = "publish_exception"
        schedule.save(update_fields=["status", "completed_at", "last_error"])
        return False

    schedule.status = PolicyScheduleStatus.COMPLETED
    schedule.completed_at = timezone.now()
    schedule.last_error = None
    schedule.save(update_fields=["status", "completed_at", "last_error"])
    return True
