from __future__ import annotations

import pytest
from django.urls import reverse

from apps.devices.inventory import replace_installed_inventory
from apps.devices.models import InstalledApplication
from apps.devices.services import create_enrollment_session
from apps.policies.lifecycle import publish_version
from apps.policies.assignments import assign_policy_to_device, create_policy

from tests.test_device_phase2 import _ec_pair, _enroll_payload

pytestmark = pytest.mark.django_db


def _enroll(client, owner_bundle):
    created = create_enrollment_session(
        organization=owner_bundle["org"],
        created_by=owner_bundle["user"],
        allowed_provisioning_modes=["device_owner", "lab_adb"],
    )
    _, pem = _ec_pair()
    response = client.post(
        "/api/v1/device/enroll",
        _enroll_payload(created.session, created.raw_secret, pem),
        content_type="application/json",
    )
    assert response.status_code == 201
    return response.json()


def _app(package="com.example.game", label="Game", version_name="1.0", version_code=10):
    return {
        "package_name": package,
        "label": label,
        "version_name": version_name,
        "version_code": version_code,
    }


def test_device_uploads_its_own_inventory(client, owner_bundle):
    enrolled = _enroll(client, owner_bundle)
    auth = {"HTTP_AUTHORIZATION": f"Bearer {enrolled['access_token']}"}
    response = client.post(
        "/api/v1/device/installed-apps",
        {"device_id": "not-the-owner", "complete": True, "apps": [_app()]},
        content_type="application/json",
        **auth,
    )
    assert response.status_code == 200
    assert response.json()["reported"] == 1
    row = InstalledApplication.objects.get(device_id=enrolled["device_id"])
    assert row.package_name == "com.example.game"
    assert row.label == "Game"
    assert row.version_code == 10
    assert row.removed_at is None
    assert InstalledApplication.objects.filter(package_name="not-the-owner").count() == 0


def test_second_device_cannot_replace_first_inventory(client, owner_bundle):
    first = _enroll(client, owner_bundle)
    auth_first = {"HTTP_AUTHORIZATION": f"Bearer {first['access_token']}"}
    client.post(
        "/api/v1/device/installed-apps",
        {"complete": True, "apps": [_app("com.example.one", "One")]},
        content_type="application/json",
        **auth_first,
    )
    second = _enroll(client, owner_bundle)
    auth_second = {"HTTP_AUTHORIZATION": f"Bearer {second['access_token']}"}
    response = client.post(
        "/api/v1/device/installed-apps",
        {"device_id": first["device_id"], "complete": True, "apps": [_app("com.example.two", "Two")]},
        content_type="application/json",
        **auth_second,
    )
    assert response.status_code == 200
    assert InstalledApplication.objects.filter(device_id=first["device_id"], removed_at__isnull=True).count() == 1
    assert InstalledApplication.objects.get(device_id=first["device_id"]).package_name == "com.example.one"
    assert InstalledApplication.objects.get(device_id=second["device_id"]).package_name == "com.example.two"


def test_later_report_marks_missing_package_removed(client, owner_bundle):
    enrolled = _enroll(client, owner_bundle)
    auth = {"HTTP_AUTHORIZATION": f"Bearer {enrolled['access_token']}"}
    client.post(
        "/api/v1/device/installed-apps",
        {"complete": True, "apps": [_app("com.example.keep", "Keep"), _app("com.example.gone", "Gone")]},
        content_type="application/json",
        **auth,
    )
    response = client.post(
        "/api/v1/device/installed-apps",
        {"complete": True, "apps": [_app("com.example.keep", "Keep", version_code=11)]},
        content_type="application/json",
        **auth,
    )
    assert response.json()["marked_removed"] == 1
    assert InstalledApplication.objects.filter(device_id=enrolled["device_id"]).count() == 2
    kept = InstalledApplication.objects.get(package_name="com.example.keep")
    gone = InstalledApplication.objects.get(package_name="com.example.gone")
    assert kept.removed_at is None
    assert kept.version_code == 11
    assert gone.removed_at is not None


def test_invalid_package_and_version_and_oversized_are_rejected(client, owner_bundle, settings):
    enrolled = _enroll(client, owner_bundle)
    auth = {"HTTP_AUTHORIZATION": f"Bearer {enrolled['access_token']}"}
    bad_name = client.post(
        "/api/v1/device/installed-apps",
        {"complete": True, "apps": [_app("not a package")]},
        content_type="application/json",
        **auth,
    )
    assert bad_name.status_code == 400
    assert bad_name.json()["code"] == "invalid_package_name"
    bad_code = client.post(
        "/api/v1/device/installed-apps",
        {"complete": True, "apps": [_app(version_code=-1)]},
        content_type="application/json",
        **auth,
    )
    assert bad_code.status_code == 400
    assert bad_code.json()["code"] == "invalid_version_code"
    settings.INSTALLED_APP_MAX_BATCH = 1
    oversized = client.post(
        "/api/v1/device/installed-apps",
        {"complete": True, "apps": [_app("com.example.one", "One"), _app("com.example.two", "Two")]},
        content_type="application/json",
        **auth,
    )
    assert oversized.status_code == 400
    assert oversized.json()["code"] == "inventory_too_large"
    assert InstalledApplication.objects.filter(device_id=enrolled["device_id"]).count() == 0


def test_owner_and_viewer_can_read_inventory_other_org_cannot(
    client, owner_bundle, viewer_user, other_bundle, password
):
    enrolled = _enroll(client, owner_bundle)
    device_id = enrolled["device_id"]
    auth = {"HTTP_AUTHORIZATION": f"Bearer {enrolled['access_token']}"}
    client.post(
        "/api/v1/device/installed-apps",
        {"complete": True, "apps": [_app()]},
        content_type="application/json",
        **auth,
    )
    client.post("/login/", {"username": owner_bundle["user"].email, "password": password})
    owner = client.get(f"/api/v1/devices/{device_id}/installed-apps")
    assert owner.status_code == 200
    assert owner.json()["apps"][0]["package_name"] == "com.example.game"
    client.post("/api/v1/auth/logout")
    client.post("/login/", {"username": viewer_user.email, "password": password})
    viewer = client.get(f"/api/v1/devices/{device_id}/installed-apps")
    assert viewer.status_code == 200
    location = client.get(f"/api/v1/devices/{device_id}/location/latest")
    assert location.status_code == 403
    client.post("/api/v1/auth/logout")
    client.post("/login/", {"username": other_bundle["user"].email, "password": password})
    foreign = client.get(f"/api/v1/devices/{device_id}/installed-apps")
    assert foreign.status_code == 404


def test_heartbeat_response_shape_unchanged(client, owner_bundle):
    enrolled = _enroll(client, owner_bundle)
    auth = {"HTTP_AUTHORIZATION": f"Bearer {enrolled['access_token']}"}
    response = client.post(
        "/api/v1/device/heartbeat",
        {
            "app_version": "0.3.2",
            "android_version": "14",
            "manufacturer": "TECNO",
            "model": "KG5j",
            "management_active": True,
            "management_mode": "device_owner",
            "connectivity": "online",
            "battery_level": 80,
            "dpc_version": "0.3.2",
        },
        content_type="application/json",
        **auth,
    )
    assert response.status_code == 200
    body = response.json()
    assert "last_seen_at" in body
    assert "policy_assignment_state" in body
    assert "apps" not in body


def test_enrollment_still_returns_device_token(client, owner_bundle):
    enrolled = _enroll(client, owner_bundle)
    assert enrolled["device_id"]
    assert enrolled["access_token"]
    assert "installed_apps" not in enrolled


def test_policy_ack_still_marks_applied(client, owner_bundle):
    enrolled = _enroll(client, owner_bundle)
    from apps.devices.models import Device

    device = Device.objects.get(pk=enrolled["device_id"])
    policy, draft = create_policy(organization=owner_bundle["org"], name="Inventory rules", actor_user=owner_bundle["user"])
    published = publish_version(organization=owner_bundle["org"], version_id=draft.id, actor_user=owner_bundle["user"])
    assign_policy_to_device(
        organization=owner_bundle["org"],
        device_id=device.id,
        policy_id=policy.id,
        actor_user=owner_bundle["user"],
    )
    auth = {"HTTP_AUTHORIZATION": f"Bearer {enrolled['access_token']}"}
    pulled = client.get("/api/v1/device/policy", **auth)
    assert pulled.status_code == 200
    ack = client.post(
        "/api/v1/device/policy/ack",
        {
            "policy_version_id": str(published.id),
            "version_number": published.version_number,
            "content_hash": published.content_hash,
            "applied_at": "2026-10-02T07:00:00Z",
            "result": "applied",
            "client_event_id": "11111111-1111-1111-1111-111111111111",
        },
        content_type="application/json",
        **auth,
    )
    assert ack.status_code == 200
    assert ack.json()["applied_updated"] is True
    device.status.refresh_from_db()
    assert device.status.applied_policy_version == published.version_number


def test_truncated_inventory_does_not_mark_missing_removed_and_updates_reported(client, owner_bundle):
    enrolled = _enroll(client, owner_bundle)
    auth = {"HTTP_AUTHORIZATION": f"Bearer {enrolled['access_token']}"}
    client.post(
        "/api/v1/device/installed-apps",
        {
            "complete": True,
            "apps": [_app("com.example.keep", "Keep", version_code=1), _app("com.example.extra", "Extra")],
        },
        content_type="application/json",
        **auth,
    )
    partial = client.post(
        "/api/v1/device/installed-apps",
        {
            "complete": False,
            "apps": [_app("com.example.keep", "Keep updated", version_code=2)],
        },
        content_type="application/json",
        **auth,
    )
    assert partial.status_code == 200
    assert partial.json()["marked_removed"] == 0
    assert partial.json()["complete"] is False
    keep = InstalledApplication.objects.get(package_name="com.example.keep")
    extra = InstalledApplication.objects.get(package_name="com.example.extra")
    assert keep.label == "Keep updated"
    assert keep.version_code == 2
    assert keep.removed_at is None
    assert extra.removed_at is None


def test_reported_package_becomes_active_again(client, owner_bundle):
    enrolled = _enroll(client, owner_bundle)
    auth = {"HTTP_AUTHORIZATION": f"Bearer {enrolled['access_token']}"}
    client.post(
        "/api/v1/device/installed-apps",
        {"complete": True, "apps": [_app("com.example.back", "Back"), _app("com.example.stay", "Stay")]},
        content_type="application/json",
        **auth,
    )
    client.post(
        "/api/v1/device/installed-apps",
        {"complete": True, "apps": [_app("com.example.stay", "Stay")]},
        content_type="application/json",
        **auth,
    )
    removed = InstalledApplication.objects.get(package_name="com.example.back")
    assert removed.removed_at is not None
    client.post(
        "/api/v1/device/installed-apps",
        {"complete": False, "apps": [_app("com.example.back", "Back again", version_code=4)]},
        content_type="application/json",
        **auth,
    )
    removed.refresh_from_db()
    stay = InstalledApplication.objects.get(package_name="com.example.stay")
    assert removed.removed_at is None
    assert removed.label == "Back again"
    assert stay.removed_at is None


def test_failed_upload_does_not_change_removed_at(client, owner_bundle):
    enrolled = _enroll(client, owner_bundle)
    auth = {"HTTP_AUTHORIZATION": f"Bearer {enrolled['access_token']}"}
    client.post(
        "/api/v1/device/installed-apps",
        {"complete": True, "apps": [_app("com.example.keep", "Keep"), _app("com.example.gone", "Gone")]},
        content_type="application/json",
        **auth,
    )
    client.post(
        "/api/v1/device/installed-apps",
        {"complete": True, "apps": [_app("com.example.keep", "Keep")]},
        content_type="application/json",
        **auth,
    )
    gone_before = InstalledApplication.objects.get(package_name="com.example.gone").removed_at
    failed = client.post(
        "/api/v1/device/installed-apps",
        {"complete": True, "apps": [_app("not a package")]},
        content_type="application/json",
        **auth,
    )
    assert failed.status_code == 400
    gone = InstalledApplication.objects.get(package_name="com.example.gone")
    keep = InstalledApplication.objects.get(package_name="com.example.keep")
    assert gone.removed_at == gone_before
    assert keep.removed_at is None


def test_empty_complete_inventory_marks_current_apps_removed(client, owner_bundle):
    enrolled = _enroll(client, owner_bundle)
    auth = {"HTTP_AUTHORIZATION": f"Bearer {enrolled['access_token']}"}
    client.post(
        "/api/v1/device/installed-apps",
        {"complete": True, "apps": [_app()]},
        content_type="application/json",
        **auth,
    )
    emptied = client.post(
        "/api/v1/device/installed-apps",
        {"complete": True, "apps": []},
        content_type="application/json",
        **auth,
    )
    assert emptied.status_code == 200
    assert emptied.json()["marked_removed"] == 1
    assert InstalledApplication.objects.get(package_name="com.example.game").removed_at is not None
    untouched = client.post(
        "/api/v1/device/installed-apps",
        {"complete": False, "apps": []},
        content_type="application/json",
        **auth,
    )
    assert untouched.status_code == 200
    assert untouched.json()["marked_removed"] == 0
    assert InstalledApplication.objects.get(package_name="com.example.game").removed_at is not None


def test_dashboard_shows_presence_and_current_apps(client, owner_bundle, password):
    enrolled = _enroll(client, owner_bundle)
    from apps.devices.models import Device

    phone = Device.objects.get(pk=enrolled["device_id"])
    replace_installed_inventory(
        device=phone,
        apps=[
            {
                "package_name": "com.example.game",
                "label": "Game",
                "version_name": "1.2",
                "version_code": 3,
            }
        ],
        complete=True,
    )
    client.post("/login/", {"username": owner_bundle["user"].email, "password": password})
    page = client.get(reverse("dashboard:device_detail", args=[phone.id]))
    assert page.status_code == 200
    body = page.content.decode()
    assert "Android version" in body
    assert "Presence" in body
    assert "Assigned policy" in body
    assert "com.example.game" in body
