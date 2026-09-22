from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from django.db.models.deletion import ProtectedError

from apps.devices.models import Device, ManagementMode
from apps.policies.models import DevicePolicyAssignment, Policy, PolicyVersion, PolicyVersionStatus

pytestmark = pytest.mark.django_db

EMPTY_POLICY_DOCUMENT = {
    "schema_version": 1,
    "internet": {},
    "calls": {},
    "applications": {},
    "screen_time": {},
    "device": {},
    "location": {},
}


@pytest.fixture
def other_device(other_bundle):
    return Device.objects.create(
        organization=other_bundle["org"],
        display_name="Other kid phone",
        management_mode=ManagementMode.DEVICE_OWNER,
    )


@pytest.fixture
def policy(owner_bundle):
    return Policy.objects.create(
        organization=owner_bundle["org"],
        name="Default",
        description="Family default",
        created_by=owner_bundle["user"],
    )


def test_policy_belongs_to_organization(policy, owner_bundle):
    assert policy.organization_id == owner_bundle["org"].id
    assert owner_bundle["org"].policies.filter(pk=policy.pk).exists()


def test_active_policy_name_unique_within_organization(owner_bundle):
    Policy.objects.create(organization=owner_bundle["org"], name="School night")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Policy.objects.create(organization=owner_bundle["org"], name="School night")


def test_active_policy_name_unique_is_organization_scoped(owner_bundle, other_bundle):
    Policy.objects.create(organization=owner_bundle["org"], name="Shared name")
    other = Policy.objects.create(organization=other_bundle["org"], name="Shared name")
    assert other.organization_id == other_bundle["org"].id


def test_archived_policy_allows_reuse_of_name(owner_bundle):
    archived = Policy.objects.create(
        organization=owner_bundle["org"],
        name="Curfew",
        archived_at=timezone.now(),
    )
    replacement = Policy.objects.create(organization=owner_bundle["org"], name="Curfew")
    assert archived.archived_at is not None
    assert replacement.archived_at is None
    assert Policy.objects.filter(organization=owner_bundle["org"], name="Curfew").count() == 2


def test_version_number_unique_per_policy(policy, owner_bundle):
    PolicyVersion.objects.create(
        policy=policy,
        organization=owner_bundle["org"],
        version_number=1,
        document=EMPTY_POLICY_DOCUMENT,
    )
    with pytest.raises((IntegrityError, ValidationError)):
        with transaction.atomic():
            PolicyVersion.objects.create(
                policy=policy,
                organization=owner_bundle["org"],
                version_number=1,
                document=EMPTY_POLICY_DOCUMENT,
            )


def test_different_policies_can_each_have_version_1(owner_bundle):
    first = Policy.objects.create(organization=owner_bundle["org"], name="A")
    second = Policy.objects.create(organization=owner_bundle["org"], name="B")
    v1 = PolicyVersion.objects.create(
        policy=first,
        organization=owner_bundle["org"],
        version_number=1,
        document=EMPTY_POLICY_DOCUMENT,
    )
    v2 = PolicyVersion.objects.create(
        policy=second,
        organization=owner_bundle["org"],
        version_number=1,
        document=EMPTY_POLICY_DOCUMENT,
    )
    assert v1.version_number == v2.version_number == 1


def test_only_one_published_version_per_policy(policy, owner_bundle):
    PolicyVersion.objects.create(
        policy=policy,
        organization=owner_bundle["org"],
        version_number=1,
        status=PolicyVersionStatus.PUBLISHED,
        document=EMPTY_POLICY_DOCUMENT,
        published_at=timezone.now(),
        content_hash="sha256:abc",
    )
    with pytest.raises((IntegrityError, ValidationError)):
        with transaction.atomic():
            PolicyVersion.objects.create(
                policy=policy,
                organization=owner_bundle["org"],
                version_number=2,
                status=PolicyVersionStatus.PUBLISHED,
                document=EMPTY_POLICY_DOCUMENT,
                published_at=timezone.now(),
                content_hash="sha256:def",
            )


def test_different_policies_can_each_have_published_version(owner_bundle):
    first = Policy.objects.create(organization=owner_bundle["org"], name="Pub A")
    second = Policy.objects.create(organization=owner_bundle["org"], name="Pub B")
    PolicyVersion.objects.create(
        policy=first,
        organization=owner_bundle["org"],
        version_number=1,
        status=PolicyVersionStatus.PUBLISHED,
        document=EMPTY_POLICY_DOCUMENT,
        published_at=timezone.now(),
    )
    PolicyVersion.objects.create(
        policy=second,
        organization=owner_bundle["org"],
        version_number=1,
        status=PolicyVersionStatus.PUBLISHED,
        document=EMPTY_POLICY_DOCUMENT,
        published_at=timezone.now(),
    )
    assert (
        PolicyVersion.objects.filter(
            organization=owner_bundle["org"],
            status=PolicyVersionStatus.PUBLISHED,
        ).count()
        == 2
    )


def test_device_policy_assignment_one_to_one(device, policy, owner_bundle):
    DevicePolicyAssignment.objects.create(
        organization=owner_bundle["org"],
        device=device,
        policy=policy,
        assigned_by=owner_bundle["user"],
    )
    with pytest.raises((IntegrityError, ValidationError)):
        with transaction.atomic():
            DevicePolicyAssignment.objects.create(
                organization=owner_bundle["org"],
                device=device,
                policy=policy,
            )


def test_cross_organization_assignment_rejected(device, other_bundle, owner_bundle):
    foreign_policy = Policy.objects.create(organization=other_bundle["org"], name="Foreign")
    with pytest.raises(ValidationError):
        DevicePolicyAssignment.objects.create(
            organization=owner_bundle["org"],
            device=device,
            policy=foreign_policy,
        )


def test_cross_organization_assignment_org_mismatch_device(other_device, policy, owner_bundle):
    with pytest.raises(ValidationError):
        DevicePolicyAssignment.objects.create(
            organization=owner_bundle["org"],
            device=other_device,
            policy=policy,
        )


def test_cross_policy_pinned_version_rejected(device, policy, owner_bundle):
    other_policy = Policy.objects.create(organization=owner_bundle["org"], name="Other")
    foreign_version = PolicyVersion.objects.create(
        policy=other_policy,
        organization=owner_bundle["org"],
        version_number=1,
        document=EMPTY_POLICY_DOCUMENT,
    )
    with pytest.raises(ValidationError):
        DevicePolicyAssignment.objects.create(
            organization=owner_bundle["org"],
            device=device,
            policy=policy,
            pinned_version=foreign_version,
        )


def test_policy_version_organization_must_match_policy(policy, other_bundle):
    with pytest.raises(ValidationError):
        PolicyVersion.objects.create(
            policy=policy,
            organization=other_bundle["org"],
            version_number=1,
            document=EMPTY_POLICY_DOCUMENT,
        )


def test_json_document_storage(policy, owner_bundle):
    version = PolicyVersion.objects.create(
        policy=policy,
        organization=owner_bundle["org"],
        version_number=1,
        schema_version=1,
        document=EMPTY_POLICY_DOCUMENT,
        status=PolicyVersionStatus.DRAFT,
    )
    reloaded = PolicyVersion.objects.get(pk=version.pk)
    assert reloaded.document == EMPTY_POLICY_DOCUMENT
    assert reloaded.document["schema_version"] == 1
    assert set(reloaded.document.keys()) == {
        "schema_version",
        "internet",
        "calls",
        "applications",
        "screen_time",
        "device",
        "location",
    }


def test_published_version_document_is_immutable(policy, owner_bundle):
    version = PolicyVersion.objects.create(
        policy=policy,
        organization=owner_bundle["org"],
        version_number=1,
        status=PolicyVersionStatus.PUBLISHED,
        document=EMPTY_POLICY_DOCUMENT,
        published_at=timezone.now(),
        content_hash="sha256:fixed",
    )
    version.document = {**EMPTY_POLICY_DOCUMENT, "internet": {"blocked": True}}
    with pytest.raises(ValueError, match="immutable"):
        version.save()


def test_superseded_version_document_is_immutable(policy, owner_bundle):
    version = PolicyVersion.objects.create(
        policy=policy,
        organization=owner_bundle["org"],
        version_number=1,
        status=PolicyVersionStatus.SUPERSEDED,
        document=EMPTY_POLICY_DOCUMENT,
        published_at=timezone.now(),
        superseded_at=timezone.now(),
        content_hash="sha256:fixed",
    )
    version.document = {**EMPTY_POLICY_DOCUMENT, "internet": {"blocked": True}}
    with pytest.raises(ValueError, match="immutable"):
        version.save()


def test_policy_protects_versions_from_cascade_delete(policy, owner_bundle):
    PolicyVersion.objects.create(
        policy=policy,
        organization=owner_bundle["org"],
        version_number=1,
        document=EMPTY_POLICY_DOCUMENT,
    )
    with pytest.raises(ProtectedError):
        policy.delete()
    assert Policy.objects.filter(pk=policy.pk).exists()
    assert PolicyVersion.objects.filter(policy=policy).count() == 1
