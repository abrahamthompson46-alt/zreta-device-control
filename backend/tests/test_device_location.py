from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from django.conf import settings
from django.core.management import call_command
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.devices.location import ingest_locations, purge_expired_locations
from apps.devices.models import Device, LocationRecord
from apps.devices.services import create_enrollment_session, revoke_device

from tests.test_device_phase2 import _assertion, _ec_pair, _enroll_payload


def _login(client, email, password):
    return client.post("/login/", {"username": email, "password": password})


def _enroll_device(client, enrollment):
    private_key, pem = _ec_pair()
    response = client.post(
        "/api/v1/device/enroll",
        _enroll_payload(enrollment.session, enrollment.raw_secret, pem),
        content_type="application/json",
    )
    assert response.status_code == 201, response.content
    body = response.json()
    return private_key, body


def _point(**overrides):
    payload = {
        "client_event_id": str(uuid.uuid4()),
        "captured_at": timezone.now().isoformat().replace("+00:00", "Z"),
        "latitude": 51.507351,
        "longitude": -0.127758,
        "accuracy_m": 12.5,
        "source": "fused",
        "is_mock": False,
        "location_disclosure_accepted": True,
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def enrollment(owner_bundle):
    return create_enrollment_session(
        organization=owner_bundle["org"],
        created_by=owner_bundle["user"],
        allowed_provisioning_modes=["device_owner", "lab_adb"],
    )


@pytest.mark.django_db
def test_upload_rejected_when_disabled(client, enrollment):
    _, enrolled = _enroll_device(client, enrollment)
    auth = {"HTTP_AUTHORIZATION": f"Bearer {enrolled['access_token']}"}
    response = client.post(
        "/api/v1/device/location",
        {"locations": [_point()]},
        content_type="application/json",
        **auth,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] == []
    assert body["rejected"][0]["code"] == "disabled"
    assert LocationRecord.objects.count() == 0
    event = AuditEvent.objects.get(action="location.rejected")
    blob = str(event.new_snapshot)
    assert "51.507" not in blob
    assert "latitude" not in blob or event.new_snapshot.get("latitude") in (None, "[redacted]")


@pytest.mark.django_db
def test_upload_requires_disclosure(client, enrollment, owner_bundle, password):
    _, enrolled = _enroll_device(client, enrollment)
    device = Device.objects.get(pk=enrolled["device_id"])
    _login(client, owner_bundle["user"].email, password)
    enable = client.post(f"/api/v1/devices/{device.id}/location/enable")
    assert enable.status_code == 200
    auth = {"HTTP_AUTHORIZATION": f"Bearer {enrolled['access_token']}"}
    point = _point(location_disclosure_accepted=False)
    response = client.post(
        "/api/v1/device/location",
        {"locations": [point]},
        content_type="application/json",
        **auth,
    )
    assert response.status_code == 200
    assert response.json()["rejected"][0]["code"] == "disclosure_required"


@pytest.mark.django_db
def test_upload_success_and_heartbeat_has_flag_not_coordinates(client, enrollment, owner_bundle, password):
    _, enrolled = _enroll_device(client, enrollment)
    device = Device.objects.get(pk=enrolled["device_id"])
    _login(client, owner_bundle["user"].email, password)
    assert client.post(f"/api/v1/devices/{device.id}/location/enable").status_code == 200
    auth = {"HTTP_AUTHORIZATION": f"Bearer {enrolled['access_token']}"}
    me = client.get("/api/v1/device/me", **auth)
    assert me.json()["location_collection_enabled"] is True
    point = _point()
    response = client.post(
        "/api/v1/device/location",
        {"locations": [point]},
        content_type="application/json",
        **auth,
    )
    assert response.status_code == 200
    assert point["client_event_id"] in response.json()["accepted"]
    assert LocationRecord.objects.filter(device=device).count() == 1
    accepted = AuditEvent.objects.get(action="location.accepted")
    assert "51.507" not in str(accepted.new_snapshot)
    beat = client.post(
        "/api/v1/device/heartbeat",
        {
            "app_version": "0.3.0",
            "management_active": False,
            "management_mode": "device_owner",
            "connectivity": "online",
            "dpc_version": "0.3.0",
        },
        content_type="application/json",
        **auth,
    )
    assert beat.status_code == 200
    beat_body = beat.json()
    assert beat_body["location_collection_enabled"] is True
    assert "latitude" not in beat_body
    assert "longitude" not in beat_body
    latest = client.get(f"/api/v1/devices/{device.id}/location/latest")
    assert latest.status_code == 200
    loc = latest.json()["location"]
    assert loc["latitude"].startswith("51.507")
    assert "openstreetmap.org" in loc["osm_url"]


@pytest.mark.django_db
def test_invalid_coordinates_and_batch_size(client, enrollment, owner_bundle, password):
    _, enrolled = _enroll_device(client, enrollment)
    device = Device.objects.get(pk=enrolled["device_id"])
    _login(client, owner_bundle["user"].email, password)
    client.post(f"/api/v1/devices/{device.id}/location/enable")
    auth = {"HTTP_AUTHORIZATION": f"Bearer {enrolled['access_token']}"}
    bad = client.post(
        "/api/v1/device/location",
        {"locations": [_point(latitude=200)]},
        content_type="application/json",
        **auth,
    )
    assert bad.json()["rejected"][0]["code"] == "invalid_coordinates"
    huge = client.post(
        "/api/v1/device/location",
        {"locations": [_point() for _ in range(21)]},
        content_type="application/json",
        **auth,
    )
    assert huge.status_code == 400
    assert huge.json()["code"] == "invalid_batch"


@pytest.mark.django_db
def test_rate_limit_twelve_per_hour(client, enrollment, owner_bundle, password):
    _, enrolled = _enroll_device(client, enrollment)
    device = Device.objects.get(pk=enrolled["device_id"])
    _login(client, owner_bundle["user"].email, password)
    client.post(f"/api/v1/devices/{device.id}/location/enable")
    auth = {"HTTP_AUTHORIZATION": f"Bearer {enrolled['access_token']}"}
    for _ in range(12):
        ok = client.post(
            "/api/v1/device/location",
            {"locations": [_point()]},
            content_type="application/json",
            **auth,
        )
        assert ok.json()["accepted"]
    extra = client.post(
        "/api/v1/device/location",
        {"locations": [_point()]},
        content_type="application/json",
        **auth,
    )
    assert extra.status_code == 429
    assert extra.json()["rejected"][0]["code"] == "rate_limited"


@pytest.mark.django_db
def test_duplicate_client_event_id_is_idempotent(client, enrollment, owner_bundle, password):
    _, enrolled = _enroll_device(client, enrollment)
    device = Device.objects.get(pk=enrolled["device_id"])
    _login(client, owner_bundle["user"].email, password)
    client.post(f"/api/v1/devices/{device.id}/location/enable")
    auth = {"HTTP_AUTHORIZATION": f"Bearer {enrolled['access_token']}"}
    point = _point()
    first = client.post("/api/v1/device/location", {"locations": [point]}, content_type="application/json", **auth)
    second = client.post("/api/v1/device/location", {"locations": [point]}, content_type="application/json", **auth)
    assert first.json()["accepted"]
    assert point["client_event_id"] in second.json()["duplicates"]
    assert LocationRecord.objects.filter(device=device).count() == 1


@pytest.mark.django_db
def test_viewer_forbidden_and_cross_tenant(client, enrollment, owner_bundle, other_bundle, viewer_user, password):
    _, enrolled = _enroll_device(client, enrollment)
    device = Device.objects.get(pk=enrolled["device_id"])
    _login(client, viewer_user.email, password)
    assert client.get(f"/api/v1/devices/{device.id}/location/latest").status_code == 403
    assert client.get(f"/api/v1/devices/{device.id}/location/history").status_code == 403
    assert client.post(f"/api/v1/devices/{device.id}/location/enable").status_code == 403
    client.logout()
    _login(client, other_bundle["user"].email, other_bundle["password"])
    assert client.get(f"/api/v1/devices/{device.id}/location/latest").status_code == 404


@pytest.mark.django_db
def test_revoked_device_cannot_upload(client, enrollment, owner_bundle, password):
    _, enrolled = _enroll_device(client, enrollment)
    device = Device.objects.get(pk=enrolled["device_id"])
    _login(client, owner_bundle["user"].email, password)
    client.post(f"/api/v1/devices/{device.id}/location/enable")
    revoke_device(device=device, actor_user=owner_bundle["user"])
    response = client.post(
        "/api/v1/device/location",
        {"locations": [_point()]},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {enrolled['access_token']}",
    )
    assert response.status_code in (401, 403)


@pytest.mark.django_db
def test_retention_purge(owner_bundle, device):
    old = timezone.now() - timedelta(days=settings.LOCATION_RETENTION_DAYS + 1)
    LocationRecord.objects.create(
        organization=owner_bundle["org"],
        device=device,
        client_event_id=uuid.uuid4(),
        captured_at=old,
        latitude="1.000000",
        longitude="2.000000",
        source="fused",
    )
    LocationRecord.objects.create(
        organization=owner_bundle["org"],
        device=device,
        client_event_id=uuid.uuid4(),
        captured_at=timezone.now(),
        latitude="3.000000",
        longitude="4.000000",
        source="fused",
    )
    deleted = purge_expired_locations()
    assert deleted >= 1
    assert LocationRecord.objects.filter(device=device).count() == 1
    call_command("purge_location_records")


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(
    "sqlite" in settings.DATABASES["default"]["ENGINE"],
    reason="requires PostgreSQL unique constraint concurrency",
)
def test_concurrent_duplicate_location_submissions(owner_bundle, device):
    device.location_collection_enabled = True
    device.save(update_fields=["location_collection_enabled"])
    event_id = uuid.uuid4()
    captured = timezone.now()
    results: list[str] = []

    def worker():
        from django.db import connection

        try:
            result = ingest_locations(
                device=device,
                items=[
                    {
                        "client_event_id": str(event_id),
                        "captured_at": captured.isoformat(),
                        "latitude": 10.0,
                        "longitude": 20.0,
                        "accuracy_m": 5,
                        "source": "fused",
                        "is_mock": False,
                        "location_disclosure_accepted": True,
                    }
                ],
            )
            if result["accepted"] or result["duplicates"]:
                results.append("ok")
            else:
                results.append("fail")
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: worker(), range(2)))
    assert LocationRecord.objects.filter(device=device, client_event_id=event_id).count() == 1
    assert results.count("ok") == 2
