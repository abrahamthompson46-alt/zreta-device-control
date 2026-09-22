from __future__ import annotations

import uuid

import pytest

from apps.audit.models import AuditEvent
from apps.devices.services import create_enrollment_session
from apps.policies.assignments import assign_policy_to_device, create_policy
from apps.policies.lifecycle import create_draft_version, publish_version
from apps.policies.models import PolicyVersionStatus
from apps.policies.schema import empty_policy_document

from tests.test_device_phase2 import _ec_pair, _enroll_payload

pytestmark = pytest.mark.django_db


@pytest.fixture
def enrollment(owner_bundle):
    return create_enrollment_session(
        organization=owner_bundle["org"],
        created_by=owner_bundle["user"],
        allowed_provisioning_modes=["device_owner", "lab_adb"],
    )


def _enroll(client, enrollment):
    private_key, pem = _ec_pair()
    response = client.post(
        "/api/v1/device/enroll",
        _enroll_payload(enrollment.session, enrollment.raw_secret, pem),
        content_type="application/json",
    )
    assert response.status_code == 201
    return private_key, response.json()


def _setup_assigned_published(client, enrollment, owner_bundle, name="Rules"):
    from apps.devices.models import Device

    _, enrolled = _enroll(client, enrollment)
    device = Device.objects.get(pk=enrolled["device_id"])
    policy, draft = create_policy(
        organization=owner_bundle["org"],
        name=name,
        actor_user=owner_bundle["user"],
    )
    published = publish_version(
        organization=owner_bundle["org"],
        version_id=draft.id,
        actor_user=owner_bundle["user"],
    )
    assign_policy_to_device(
        organization=owner_bundle["org"],
        device_id=device.id,
        policy_id=policy.id,
        actor_user=owner_bundle["user"],
    )
    auth = {"HTTP_AUTHORIZATION": f"Bearer {enrolled['access_token']}"}
    return device, policy, published, auth, enrolled


def test_device_policy_unassigned(client, enrollment):
    _, enrolled = _enroll(client, enrollment)
    auth = {"HTTP_AUTHORIZATION": f"Bearer {enrolled['access_token']}"}
    response = client.get("/api/v1/device/policy", **auth)
    assert response.status_code == 200
    body = response.json()
    assert body["assignment_state"] == "unassigned"
    assert body["document"] is None


def test_device_policy_pull_ack_and_etag(client, enrollment, owner_bundle):
    device, policy, published, auth, _ = _setup_assigned_published(client, enrollment, owner_bundle)
    response = client.get("/api/v1/device/policy", **auth)
    assert response.status_code == 200
    body = response.json()
    assert body["assignment_state"] == "assigned"
    assert body["policy_version_id"] == str(published.id)
    assert body["document"] == empty_policy_document()
    etag = response.headers.get("ETag")
    assert etag

    cached = client.get("/api/v1/device/policy", HTTP_IF_NONE_MATCH=etag, **auth)
    assert cached.status_code == 304

    ack = client.post(
        "/api/v1/device/policy/ack",
        {
            "policy_version_id": str(published.id),
            "version_number": published.version_number,
            "content_hash": published.content_hash,
            "applied_at": "2026-09-20T10:00:00Z",
            "result": "applied",
            "client_event_id": str(uuid.uuid4()),
        },
        content_type="application/json",
        **auth,
    )
    assert ack.status_code == 200
    assert ack.json()["accepted"] is True
    assert ack.json()["applied_updated"] is True
    device.status.refresh_from_db()
    assert device.status.applied_policy_version == published.version_number
    assert str(device.status.applied_policy_version_ref_id) == str(published.id)
    event = AuditEvent.objects.filter(action="policy.ack").latest("timestamp")
    assert "document" not in event.new_snapshot


def test_current_published_ack_updates_applied(client, enrollment, owner_bundle):
    device, _, published, auth, _ = _setup_assigned_published(
        client, enrollment, owner_bundle, name="Current"
    )
    response = client.post(
        "/api/v1/device/policy/ack",
        {
            "policy_version_id": str(published.id),
            "version_number": published.version_number,
            "content_hash": published.content_hash,
            "result": "applied",
            "client_event_id": str(uuid.uuid4()),
        },
        content_type="application/json",
        **auth,
    )
    assert response.status_code == 200
    assert response.json()["applied_updated"] is True
    device.status.refresh_from_db()
    assert device.status.applied_policy_version == published.version_number


def test_older_and_superseded_ack_does_not_overwrite(client, enrollment, owner_bundle):
    device, policy, v1, auth, _ = _setup_assigned_published(
        client, enrollment, owner_bundle, name="Rollback"
    )
    # Apply v1 first
    client.post(
        "/api/v1/device/policy/ack",
        {
            "policy_version_id": str(v1.id),
            "version_number": v1.version_number,
            "content_hash": v1.content_hash,
            "result": "applied",
            "client_event_id": str(uuid.uuid4()),
        },
        content_type="application/json",
        **auth,
    )
    device.status.refresh_from_db()
    assert device.status.applied_policy_version == 1

    draft2 = create_draft_version(
        organization=owner_bundle["org"],
        policy_id=policy.id,
        actor_user=owner_bundle["user"],
        document=empty_policy_document(),
    )
    v2 = publish_version(
        organization=owner_bundle["org"],
        version_id=draft2.id,
        actor_user=owner_bundle["user"],
    )
    # Apply current v2
    client.post(
        "/api/v1/device/policy/ack",
        {
            "policy_version_id": str(v2.id),
            "version_number": v2.version_number,
            "content_hash": v2.content_hash,
            "result": "applied",
            "client_event_id": str(uuid.uuid4()),
        },
        content_type="application/json",
        **auth,
    )
    device.status.refresh_from_db()
    assert device.status.applied_policy_version == 2
    applied_ref = device.status.applied_policy_version_ref_id

    v1.refresh_from_db()
    assert v1.status == PolicyVersionStatus.SUPERSEDED

    stale = client.post(
        "/api/v1/device/policy/ack",
        {
            "policy_version_id": str(v1.id),
            "version_number": v1.version_number,
            "content_hash": v1.content_hash,
            "result": "applied",
            "client_event_id": str(uuid.uuid4()),
        },
        content_type="application/json",
        **auth,
    )
    assert stale.status_code == 200
    assert stale.json()["applied_updated"] is False
    assert stale.json()["ack_result"] == "stale_version"
    device.status.refresh_from_db()
    assert device.status.applied_policy_version == 2
    assert device.status.applied_policy_version_ref_id == applied_ref
    assert device.status.policy_ack_result == "stale_version"


def test_draft_ack_does_not_mark_applied(client, enrollment, owner_bundle):
    device, policy, published, auth, _ = _setup_assigned_published(
        client, enrollment, owner_bundle, name="DraftAck"
    )
    client.post(
        "/api/v1/device/policy/ack",
        {
            "policy_version_id": str(published.id),
            "version_number": published.version_number,
            "content_hash": published.content_hash,
            "result": "applied",
            "client_event_id": str(uuid.uuid4()),
        },
        content_type="application/json",
        **auth,
    )
    draft = create_draft_version(
        organization=owner_bundle["org"],
        policy_id=policy.id,
        actor_user=owner_bundle["user"],
    )
    response = client.post(
        "/api/v1/device/policy/ack",
        {
            "policy_version_id": str(draft.id),
            "version_number": draft.version_number,
            "result": "applied",
            "client_event_id": str(uuid.uuid4()),
        },
        content_type="application/json",
        **auth,
    )
    assert response.status_code == 200
    assert response.json()["applied_updated"] is False
    device.status.refresh_from_db()
    assert device.status.applied_policy_version == published.version_number
    assert str(device.status.applied_policy_version_ref_id) == str(published.id)


def test_wrong_policy_version_ack_rejected(client, enrollment, owner_bundle):
    device, _, published, auth, _ = _setup_assigned_published(
        client, enrollment, owner_bundle, name="Assigned"
    )
    other, other_draft = create_policy(
        organization=owner_bundle["org"],
        name="OtherPolicy",
        actor_user=owner_bundle["user"],
    )
    other_pub = publish_version(
        organization=owner_bundle["org"],
        version_id=other_draft.id,
        actor_user=owner_bundle["user"],
    )
    response = client.post(
        "/api/v1/device/policy/ack",
        {
            "policy_version_id": str(other_pub.id),
            "version_number": other_pub.version_number,
            "content_hash": other_pub.content_hash,
            "result": "applied",
            "client_event_id": str(uuid.uuid4()),
        },
        content_type="application/json",
        **auth,
    )
    assert response.status_code == 400
    assert response.json()["code"] == "version_not_found"
    device.status.refresh_from_db()
    assert device.status.applied_policy_version_ref_id is None


def test_rejected_results_do_not_update_applied_fields(client, enrollment, owner_bundle):
    device, _, published, auth, _ = _setup_assigned_published(
        client, enrollment, owner_bundle, name="Reject"
    )
    # Establish applied state
    client.post(
        "/api/v1/device/policy/ack",
        {
            "policy_version_id": str(published.id),
            "version_number": published.version_number,
            "content_hash": published.content_hash,
            "result": "applied",
            "client_event_id": str(uuid.uuid4()),
        },
        content_type="application/json",
        **auth,
    )
    device.status.refresh_from_db()
    before_version = device.status.applied_policy_version
    before_ref = device.status.applied_policy_version_ref_id
    before_applied_at = device.status.policy_applied_at

    for result in (
        "rejected_malformed",
        "rejected_schema",
        "enforcement_partial",
        "rejected_enforcement",
    ):
        response = client.post(
            "/api/v1/device/policy/ack",
            {
                "policy_version_id": str(published.id),
                "version_number": published.version_number,
                "content_hash": published.content_hash,
                "result": result,
                "client_event_id": str(uuid.uuid4()),
            },
            content_type="application/json",
            **auth,
        )
        assert response.status_code == 200
        assert response.json()["applied_updated"] is False
        device.status.refresh_from_db()
        assert device.status.applied_policy_version == before_version
        assert device.status.applied_policy_version_ref_id == before_ref
        assert device.status.policy_applied_at == before_applied_at
        assert device.status.policy_ack_result == result
        assert device.status.policy_last_error == result


def test_device_policy_ack_idempotent(client, enrollment, owner_bundle):
    device, _, published, auth, _ = _setup_assigned_published(
        client, enrollment, owner_bundle, name="Idempotent"
    )
    event_id = str(uuid.uuid4())
    payload = {
        "policy_version_id": str(published.id),
        "version_number": published.version_number,
        "content_hash": published.content_hash,
        "result": "applied",
        "client_event_id": event_id,
    }
    first = client.post("/api/v1/device/policy/ack", payload, content_type="application/json", **auth)
    second = client.post("/api/v1/device/policy/ack", payload, content_type="application/json", **auth)
    assert first.status_code == 200
    assert first.json()["applied_updated"] is True
    assert second.status_code == 200
    assert second.json()["idempotent"] is True
    assert second.json()["applied_updated"] is False


def test_other_device_cannot_use_foreign_version(client, enrollment, owner_bundle, other_bundle):
    device, _, _, auth, enrolled = _setup_assigned_published(
        client, enrollment, owner_bundle, name="Own"
    )
    foreign_policy, foreign_draft = create_policy(
        organization=other_bundle["org"],
        name="Foreign",
        actor_user=other_bundle["user"],
    )
    foreign_published = publish_version(
        organization=other_bundle["org"],
        version_id=foreign_draft.id,
        actor_user=other_bundle["user"],
    )
    response = client.post(
        "/api/v1/device/policy/ack",
        {
            "policy_version_id": str(foreign_published.id),
            "version_number": foreign_published.version_number,
            "content_hash": foreign_published.content_hash,
            "result": "applied",
            "client_event_id": str(uuid.uuid4()),
        },
        content_type="application/json",
        **auth,
    )
    assert response.status_code == 400
    device.status.refresh_from_db()
    assert device.status.applied_policy_version_ref_id is None


def test_cross_device_ack_impossible(client, enrollment, owner_bundle):
    """Second enrollment gets its own JWT; cannot ACK first device's applied state via other token."""
    device_a, policy, published, auth_a, _ = _setup_assigned_published(
        client, enrollment, owner_bundle, name="A"
    )
    enrollment_b = create_enrollment_session(
        organization=owner_bundle["org"],
        created_by=owner_bundle["user"],
        allowed_provisioning_modes=["device_owner", "lab_adb"],
    )
    _, enrolled_b = _enroll(client, enrollment_b)
    auth_b = {"HTTP_AUTHORIZATION": f"Bearer {enrolled_b['access_token']}"}
    # Device B has no assignment — ACK of A's version fails
    response = client.post(
        "/api/v1/device/policy/ack",
        {
            "policy_version_id": str(published.id),
            "version_number": published.version_number,
            "content_hash": published.content_hash,
            "result": "applied",
            "client_event_id": str(uuid.uuid4()),
        },
        content_type="application/json",
        **auth_b,
    )
    assert response.status_code == 400
    assert response.json()["code"] in {"not_assigned", "version_not_found"}
