from __future__ import annotations

import copy
from typing import Any

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.audit.services import record_audit
from apps.policies.canonical import canonicalize_document, content_hash_for_document
from apps.policies.exceptions import PolicyError
from apps.policies.models import Policy, PolicyVersion, PolicyVersionStatus
from apps.policies.schema import empty_policy_document, validate_policy_document


def _require_version(*, version_id, organization) -> PolicyVersion:
    version = (
        PolicyVersion.objects.select_related("policy", "organization")
        .filter(pk=version_id, organization_id=organization.id)
        .first()
    )
    if version is None:
        raise PolicyError("Policy version not found in this organization.", "version_not_found")
    return version


def _next_version_number(policy: Policy) -> int:
    current = policy.versions.aggregate(max_n=Max("version_number"))["max_n"]
    return int(current or 0) + 1


def _version_audit_snapshot(version: PolicyVersion) -> dict[str, Any]:
    return {
        "policy_id": str(version.policy_id),
        "version_id": str(version.id),
        "version_number": version.version_number,
        "schema_version": version.schema_version,
        "content_hash": version.content_hash,
        "status": version.status,
    }


@transaction.atomic
def create_draft_version(
    *,
    organization,
    policy_id,
    actor_user=None,
    document: dict | None = None,
    schema_version: int | None = None,
    copy_from_version_id=None,
    request_meta: dict | None = None,
) -> PolicyVersion:
    """Create a new draft PolicyVersion. Document is not required to be publishable yet."""
    policy = (
        Policy.objects.select_for_update()
        .filter(pk=policy_id, organization_id=organization.id)
        .first()
    )
    if policy is None:
        raise PolicyError("Policy not found in this organization.", "policy_not_found")

    if copy_from_version_id is not None:
        source = (
            PolicyVersion.objects.select_for_update()
            .filter(pk=copy_from_version_id, policy_id=policy.id, organization_id=organization.id)
            .first()
        )
        if source is None:
            raise PolicyError("Source policy version not found.", "version_not_found")
        doc = copy.deepcopy(source.document)
        schema = source.schema_version
    else:
        doc = copy.deepcopy(document) if document is not None else empty_policy_document()
        if not isinstance(doc, dict):
            raise PolicyError("Policy document must be a JSON object.", "invalid_document")
        schema = schema_version if schema_version is not None else int(doc.get("schema_version") or 1)
        doc.setdefault("schema_version", schema)

    version = PolicyVersion(
        policy=policy,
        organization=policy.organization,
        version_number=_next_version_number(policy),
        schema_version=schema,
        document=doc,
        status=PolicyVersionStatus.DRAFT,
        created_by=actor_user,
    )
    version.save()

    meta = request_meta or {}
    record_audit(
        organization=organization,
        actor_user=actor_user,
        action="policy.version_created",
        result="success",
        new_snapshot=_version_audit_snapshot(version),
        **meta,
    )
    return version


@transaction.atomic
def update_draft_version(
    *,
    organization,
    version_id,
    document: dict,
    schema_version: int | None = None,
    actor_user=None,
) -> PolicyVersion:
    """Replace the document on a draft version only."""
    version = (
        PolicyVersion.objects.select_for_update()
        .select_related("policy")
        .filter(pk=version_id, organization_id=organization.id)
        .first()
    )
    if version is None:
        raise PolicyError("Policy version not found in this organization.", "version_not_found")
    if version.policy.organization_id != organization.id:
        raise PolicyError("Cross-organization policy operation denied.", "cross_organization")
    if version.status != PolicyVersionStatus.DRAFT:
        raise PolicyError("Only draft policy versions can be edited.", "not_draft")
    if not isinstance(document, dict):
        raise PolicyError("Policy document must be a JSON object.", "invalid_document")

    version.document = copy.deepcopy(document)
    if schema_version is not None:
        version.schema_version = schema_version
        version.document["schema_version"] = schema_version
    elif "schema_version" in document:
        version.schema_version = document["schema_version"]
    version.save()
    return version


@transaction.atomic
def publish_version(
    *,
    organization,
    version_id,
    actor_user=None,
    request_meta: dict | None = None,
) -> PolicyVersion:
    """Atomically publish a draft: validate, hash, supersede previous, mark published."""
    draft = (
        PolicyVersion.objects.select_related("policy")
        .filter(pk=version_id)
        .first()
    )
    if draft is None:
        raise PolicyError("Policy version not found.", "version_not_found")
    if draft.organization_id != organization.id or draft.policy.organization_id != organization.id:
        raise PolicyError("Cross-organization policy operation denied.", "cross_organization")

    policy = Policy.objects.select_for_update().get(pk=draft.policy_id)
    if policy.organization_id != organization.id:
        raise PolicyError("Cross-organization policy operation denied.", "cross_organization")

    draft = (
        PolicyVersion.objects.select_for_update()
        .select_related("policy")
        .get(pk=version_id)
    )
    if draft.organization_id != organization.id:
        raise PolicyError("Cross-organization policy operation denied.", "cross_organization")
    if draft.status != PolicyVersionStatus.DRAFT:
        raise PolicyError("Only draft policy versions can be published.", "not_draft")

    validated = validate_policy_document(draft.document)
    canonical = canonicalize_document(validated)
    digest = content_hash_for_document(canonical)
    now = timezone.now()
    meta = request_meta or {}

    previous = (
        PolicyVersion.objects.select_for_update()
        .filter(policy_id=policy.id, status=PolicyVersionStatus.PUBLISHED)
        .first()
    )
    if previous is not None:
        old_snapshot = _version_audit_snapshot(previous)
        previous.status = PolicyVersionStatus.SUPERSEDED
        previous.superseded_at = now
        previous.save()
        record_audit(
            organization=organization,
            actor_user=actor_user,
            action="policy.superseded",
            result="success",
            old_snapshot=old_snapshot,
            new_snapshot=_version_audit_snapshot(previous),
            **meta,
        )

    draft.document = canonical
    draft.schema_version = canonical["schema_version"]
    draft.content_hash = digest
    draft.status = PolicyVersionStatus.PUBLISHED
    draft.published_at = now
    draft.published_by = actor_user
    draft.save()

    record_audit(
        organization=organization,
        actor_user=actor_user,
        action="policy.published",
        result="success",
        new_snapshot=_version_audit_snapshot(draft),
        **meta,
    )
    try:
        from apps.devices.fcm import wake_devices_for_policy

        wake_devices_for_policy(
            organization_id=organization.id,
            policy_id=policy.id,
            reason="policy_published",
        )
    except Exception:
        # Wake must never fail publish.
        pass
    return draft


@transaction.atomic
def rollback_to_version(
    *,
    organization,
    target_version_id,
    actor_user=None,
    request_meta: dict | None = None,
) -> PolicyVersion:
    """Publish a NEW version whose document is a deep copy of a historical version.

    Never mutates the historical target. Goes through the same publish validation path.
    """
    target = _require_version(version_id=target_version_id, organization=organization)
    if target.status == PolicyVersionStatus.DRAFT:
        raise PolicyError("Cannot rollback to a draft version.", "invalid_rollback_target")

    # Create draft under policy lock, then publish (nested atomic joins the outer transaction).
    draft = create_draft_version(
        organization=organization,
        policy_id=target.policy_id,
        actor_user=actor_user,
        copy_from_version_id=target.id,
        request_meta=request_meta,
    )
    return publish_version(
        organization=organization,
        version_id=draft.id,
        actor_user=actor_user,
        request_meta=request_meta,
    )
