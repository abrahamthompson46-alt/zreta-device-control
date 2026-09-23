from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.devices.fcm import register_fcm_token, send_policy_wake, wake_devices_for_policy
from apps.devices.services import create_enrollment_session
from apps.policies.assignments import assign_policy_to_device, create_policy
from apps.policies.lifecycle import create_draft_version, publish_version
from apps.policies.models import PolicyScheduleStatus, PolicyVersionStatus
from apps.policies.schedules import (
    cancel_policy_schedule,
    process_due_schedules,
    schedule_policy_publish,
)
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


def test_device_fcm_token_register_and_clear(client, enrollment):
    from apps.devices.models import Device

    _, enrolled = _enroll(client, enrollment)
    device = Device.objects.get(pk=enrolled["device_id"])
    auth = {"HTTP_AUTHORIZATION": f"Bearer {enrolled['access_token']}"}

    ok = client.post(
        "/api/v1/device/fcm-token",
        {"token": "fcm-token-abc-123"},
        content_type="application/json",
        **auth,
    )
    assert ok.status_code == 200
    assert ok.json()["registered"] is True
    device.refresh_from_db()
    assert device.fcm_registration_token == "fcm-token-abc-123"
    assert device.fcm_token_updated_at is not None

    cleared = client.post(
        "/api/v1/device/fcm-token",
        {"token": ""},
        content_type="application/json",
        **auth,
    )
    assert cleared.status_code == 200
    assert cleared.json()["registered"] is False
    device.refresh_from_db()
    assert device.fcm_registration_token is None


def test_device_fcm_token_rejects_oversized(client, enrollment):
    _, enrolled = _enroll(client, enrollment)
    auth = {"HTTP_AUTHORIZATION": f"Bearer {enrolled['access_token']}"}
    response = client.post(
        "/api/v1/device/fcm-token",
        {"token": "x" * 513},
        content_type="application/json",
        **auth,
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_fcm_token"


def test_publish_wakes_assigned_devices(owner_bundle, device):
    policy, draft = create_policy(
        organization=owner_bundle["org"],
        name="Wake me",
        actor_user=owner_bundle["user"],
    )
    assign_policy_to_device(
        organization=owner_bundle["org"],
        device_id=device.id,
        policy_id=policy.id,
        actor_user=owner_bundle["user"],
    )
    register_fcm_token(device=device, token="token-for-wake")

    with patch("apps.devices.fcm.send_policy_wake") as mock_wake:
        mock_wake.return_value = {"attempted": 1, "sent": 0, "failed": 0, "skipped": "firebase_not_configured"}
        publish_version(
            organization=owner_bundle["org"],
            version_id=draft.id,
            actor_user=owner_bundle["user"],
        )
        mock_wake.assert_called_once()
        kwargs = mock_wake.call_args.kwargs
        assert "token-for-wake" in list(kwargs["tokens"])
        assert kwargs["reason"] == "policy_published"


def test_send_policy_wake_skips_without_firebase(settings):
    settings.FIREBASE_CREDENTIALS_JSON = ""
    settings.FIREBASE_CREDENTIALS_FILE = ""
    result = send_policy_wake(tokens=["a"], reason="test")
    assert result["skipped"] == "firebase_not_configured"
    assert result["attempted"] == 1
    assert result["sent"] == 0


def test_wake_devices_for_policy_empty_when_no_tokens(owner_bundle, device):
    policy, _ = create_policy(
        organization=owner_bundle["org"],
        name="No tokens",
        actor_user=owner_bundle["user"],
    )
    assign_policy_to_device(
        organization=owner_bundle["org"],
        device_id=device.id,
        policy_id=policy.id,
        actor_user=owner_bundle["user"],
    )
    result = wake_devices_for_policy(
        organization_id=owner_bundle["org"].id,
        policy_id=policy.id,
    )
    assert result["attempted"] == 0
    assert result["skipped"] == "no_tokens"


def _login(client, user, password):
    return client.post("/login/", {"username": user.email, "password": password})


def test_policy_schedule_create_process_cancel(client, owner_bundle, password):
    _login(client, owner_bundle["user"], password)
    created = client.post(
        "/api/v1/policies",
        {"name": "Scheduled"},
        content_type="application/json",
    )
    assert created.status_code == 201
    policy_id = created.json()["id"]
    version_id = created.json()["initial_version"]["id"]

    activate = (timezone.now() + timedelta(hours=2)).isoformat()
    scheduled = client.post(
        "/api/v1/policies/schedules",
        {
            "policy_id": policy_id,
            "version_id": version_id,
            "activate_at": activate,
        },
        content_type="application/json",
    )
    assert scheduled.status_code == 201
    body = scheduled.json()
    assert body["status"] == "pending"
    schedule_id = body["id"]

    listed = client.get("/api/v1/policies/schedules")
    assert listed.status_code == 200
    assert any(row["id"] == schedule_id for row in listed.json())

    # Not due yet
    result = process_due_schedules()
    assert result["due"] == 0

    from apps.policies.models import PolicySchedule

    row = PolicySchedule.objects.get(pk=schedule_id)
    row.activate_at = timezone.now() - timedelta(minutes=1)
    row.save(update_fields=["activate_at"])

    with patch("apps.devices.fcm.wake_devices_for_policy") as mock_wake:
        mock_wake.return_value = {"attempted": 0, "sent": 0, "failed": 0, "skipped": "no_tokens"}
        processed = process_due_schedules()
    assert processed["completed"] == 1
    row.refresh_from_db()
    assert row.status == PolicyScheduleStatus.COMPLETED
    from apps.policies.models import PolicyVersion

    version = PolicyVersion.objects.get(pk=version_id)
    assert version.status == PolicyVersionStatus.PUBLISHED


def test_policy_schedule_cancel_pending(client, owner_bundle, password):
    _login(client, owner_bundle["user"], password)
    created = client.post("/api/v1/policies", {"name": "Cancel me"}, content_type="application/json")
    policy_id = created.json()["id"]
    version_id = created.json()["initial_version"]["id"]
    activate = (timezone.now() + timedelta(days=1)).isoformat()
    scheduled = client.post(
        "/api/v1/policies/schedules",
        {"policy_id": policy_id, "version_id": version_id, "activate_at": activate},
        content_type="application/json",
    )
    schedule_id = scheduled.json()["id"]
    deleted = client.delete(f"/api/v1/policies/schedules/{schedule_id}")
    assert deleted.status_code == 204
    from apps.policies.models import PolicySchedule

    assert PolicySchedule.objects.get(pk=schedule_id).status == PolicyScheduleStatus.CANCELLED


def test_schedule_rejects_past_activate_at(owner_bundle):
    policy, draft = create_policy(
        organization=owner_bundle["org"],
        name="Past",
        actor_user=owner_bundle["user"],
    )
    with pytest.raises(Exception) as exc:
        schedule_policy_publish(
            organization=owner_bundle["org"],
            policy_id=policy.id,
            version_id=draft.id,
            activate_at=timezone.now() - timedelta(minutes=1),
            actor_user=owner_bundle["user"],
        )
    assert exc.value.code == "activate_at_not_future"


def test_schedule_duplicate_pending_conflict(owner_bundle):
    policy, draft = create_policy(
        organization=owner_bundle["org"],
        name="Dup",
        actor_user=owner_bundle["user"],
    )
    activate = timezone.now() + timedelta(hours=1)
    schedule_policy_publish(
        organization=owner_bundle["org"],
        policy_id=policy.id,
        version_id=draft.id,
        activate_at=activate,
        actor_user=owner_bundle["user"],
    )
    with pytest.raises(Exception) as exc:
        schedule_policy_publish(
            organization=owner_bundle["org"],
            policy_id=policy.id,
            version_id=draft.id,
            activate_at=activate + timedelta(hours=1),
            actor_user=owner_bundle["user"],
        )
    assert exc.value.code == "schedule_exists"


def test_schedule_failed_when_version_not_draft(owner_bundle):
    policy, draft = create_policy(
        organization=owner_bundle["org"],
        name="Fail sched",
        actor_user=owner_bundle["user"],
    )
    publish_version(
        organization=owner_bundle["org"],
        version_id=draft.id,
        actor_user=owner_bundle["user"],
    )
    # Create a new draft then schedule an already-published id via direct process path
    draft2 = create_draft_version(
        organization=owner_bundle["org"],
        policy_id=policy.id,
        actor_user=owner_bundle["user"],
        document=empty_policy_document(),
    )
    schedule = schedule_policy_publish(
        organization=owner_bundle["org"],
        policy_id=policy.id,
        version_id=draft2.id,
        activate_at=timezone.now() + timedelta(hours=1),
        actor_user=owner_bundle["user"],
    )
    # Force due and corrupt by publishing the draft first
    publish_version(
        organization=owner_bundle["org"],
        version_id=draft2.id,
        actor_user=owner_bundle["user"],
    )
    schedule.activate_at = timezone.now() - timedelta(seconds=5)
    schedule.save(update_fields=["activate_at"])
    result = process_due_schedules()
    assert result["failed"] == 1
    schedule.refresh_from_db()
    assert schedule.status == PolicyScheduleStatus.FAILED
    assert schedule.last_error == "not_draft"


def test_cancel_schedule_service(owner_bundle):
    policy, draft = create_policy(
        organization=owner_bundle["org"],
        name="Svc cancel",
        actor_user=owner_bundle["user"],
    )
    schedule = schedule_policy_publish(
        organization=owner_bundle["org"],
        policy_id=policy.id,
        version_id=draft.id,
        activate_at=timezone.now() + timedelta(hours=3),
        actor_user=owner_bundle["user"],
    )
    cancel_policy_schedule(
        organization=owner_bundle["org"],
        schedule_id=schedule.id,
        actor_user=owner_bundle["user"],
    )
    schedule.refresh_from_db()
    assert schedule.status == PolicyScheduleStatus.CANCELLED
