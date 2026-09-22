from __future__ import annotations

import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.conf import settings
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.devices.models import CredentialStatus, Device, DeviceCredential
from apps.devices.services import create_enrollment_session
from datetime import timedelta


def _ec_pair():
    private_key = ec.generate_private_key(ec.SECP256R1())
    pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_key, pem


def _assertion(private_key, device_id, kid, *, jti=None, exp_offset=60):
    now = int(time.time())
    return jwt.encode(
        {
            "iss": str(device_id),
            "sub": str(device_id),
            "kid": kid,
            "aud": settings.DEVICE_JWT_AUDIENCE,
            "iat": now,
            "exp": now + exp_offset,
            "jti": jti or uuid.uuid4().hex,
        },
        private_key,
        algorithm="ES256",
        headers={"alg": "ES256", "kid": kid},
    )


def _enroll_payload(session, secret, pem, kid="kid-1", **extra):
    body = {
        "enrollment_session_id": str(session.id),
        "enrollment_secret": secret,
        "disclosure_accepted": True,
        "public_key_id": kid,
        "public_key": pem,
        "management_mode": "device_owner",
        "manufacturer": "Google",
        "model": "Pixel",
        "android_version": "15",
        "dpc_version": "0.2.0",
        "display_name": "Lab phone",
    }
    body.update(extra)
    return body


@pytest.fixture
def enrollment(owner_bundle):
    created = create_enrollment_session(
        organization=owner_bundle["org"],
        created_by=owner_bundle["user"],
        allowed_provisioning_modes=["device_owner", "lab_adb"],
    )
    return created


@pytest.mark.django_db
def test_device_enroll_success(client, enrollment):
    private_key, pem = _ec_pair()
    response = client.post(
        "/api/v1/device/enroll",
        _enroll_payload(enrollment.session, enrollment.raw_secret, pem),
        content_type="application/json",
    )
    assert response.status_code == 201
    body = response.json()
    assert body["access_token"]
    assert body["expires_in"] == settings.DEVICE_ACCESS_TOKEN_TTL_SECONDS
    device = Device.objects.get(pk=body["device_id"])
    cred = device.credentials.get()
    assert cred.public_key.startswith("-----BEGIN PUBLIC KEY-----")
    assert "PRIVATE" not in cred.public_key
    assert device.organization_id == enrollment.session.organization_id
    enrollment.session.refresh_from_db()
    assert enrollment.session.status == "consumed"
    assert AuditEvent.objects.filter(action="enrollment.device_succeeded", target_device=device).exists()
    blob = str(list(AuditEvent.objects.filter(action="enrollment.device_succeeded").values()))
    assert enrollment.raw_secret not in blob
    assert private_key.private_numbers().private_value  # key exists client-side only
    assert str(private_key.private_numbers().private_value) not in blob


@pytest.mark.django_db
def test_device_enroll_rejects_private_key_pem(client, enrollment):
    private_key = ec.generate_private_key(ec.SECP256R1())
    priv_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    response = client.post(
        "/api/v1/device/enroll",
        _enroll_payload(enrollment.session, enrollment.raw_secret, priv_pem),
        content_type="application/json",
    )
    assert response.status_code == 400
    assert Device.objects.count() == 0


@pytest.mark.django_db
def test_device_enroll_invalid_secret(client, enrollment):
    _, pem = _ec_pair()
    response = client.post(
        "/api/v1/device/enroll",
        _enroll_payload(enrollment.session, "wrong-secret-value-xxxxxx", pem),
        content_type="application/json",
    )
    assert response.status_code == 400
    enrollment.session.refresh_from_db()
    assert enrollment.session.status == "pending"
    assert AuditEvent.objects.filter(action="enrollment.device_failed").exists()


@pytest.mark.django_db
def test_device_enroll_expired(client, enrollment):
    _, pem = _ec_pair()
    enrollment.session.expires_at = timezone.now() - timedelta(minutes=1)
    enrollment.session.save()
    response = client.post(
        "/api/v1/device/enroll",
        _enroll_payload(enrollment.session, enrollment.raw_secret, pem),
        content_type="application/json",
    )
    assert response.status_code == 400
    assert response.json()["code"] == "expired"


@pytest.mark.django_db
def test_device_enroll_used_twice(client, enrollment):
    _, pem = _ec_pair()
    first = client.post(
        "/api/v1/device/enroll",
        _enroll_payload(enrollment.session, enrollment.raw_secret, pem, kid="k1"),
        content_type="application/json",
    )
    assert first.status_code == 201
    second = client.post(
        "/api/v1/device/enroll",
        _enroll_payload(enrollment.session, enrollment.raw_secret, pem, kid="k2"),
        content_type="application/json",
    )
    assert second.status_code == 400
    assert second.json()["code"] == "used"


@pytest.mark.django_db
def test_device_enroll_cross_org_secret_does_not_bind_other_org(client, enrollment, other_bundle):
    _, pem = _ec_pair()
    other = create_enrollment_session(organization=other_bundle["org"], created_by=other_bundle["user"])
    response = client.post(
        "/api/v1/device/enroll",
        _enroll_payload(other.session, enrollment.raw_secret, pem),
        content_type="application/json",
    )
    assert response.status_code == 400
    assert Device.objects.filter(organization=other_bundle["org"]).count() == 0
    assert Device.objects.filter(organization=enrollment.session.organization).count() == 0


@pytest.mark.django_db
def test_device_token_and_heartbeat_and_me(client, enrollment):
    private_key, pem = _ec_pair()
    enrolled = client.post(
        "/api/v1/device/enroll",
        _enroll_payload(enrollment.session, enrollment.raw_secret, pem),
        content_type="application/json",
    ).json()
    device_id = enrolled["device_id"]
    assertion = _assertion(private_key, device_id, "kid-1")
    token_res = client.post(
        "/api/v1/device/token",
        {
            "device_id": device_id,
            "public_key_id": "kid-1",
            "client_assertion": assertion,
        },
        content_type="application/json",
    )
    assert token_res.status_code == 200
    access = token_res.json()["access_token"]
    replay = client.post(
        "/api/v1/device/token",
        {
            "device_id": device_id,
            "public_key_id": "kid-1",
            "client_assertion": assertion,
        },
        content_type="application/json",
    )
    assert replay.status_code == 401
    assert replay.json()["code"] == "replay"

    auth = {"HTTP_AUTHORIZATION": f"Bearer {access}"}
    beat = client.post(
        "/api/v1/device/heartbeat",
        {
            "app_version": "0.2.0",
            "android_version": "15",
            "management_active": True,
            "management_mode": "device_owner",
            "connectivity": "online",
            "battery_level": 77,
            "dpc_version": "0.2.0",
        },
        content_type="application/json",
        **auth,
    )
    assert beat.status_code == 200
    device = Device.objects.get(pk=device_id)
    assert device.status.battery_level == 77
    assert device.status.management_active is True
    me = client.get("/api/v1/device/me", **auth)
    assert me.status_code == 200
    assert me.json()["id"] == device_id
    assert "access_token" not in me.json()


@pytest.mark.django_db
def test_revoked_device_rejected(client, enrollment, owner_bundle):
    from apps.devices.services import revoke_device

    private_key, pem = _ec_pair()
    enrolled = client.post(
        "/api/v1/device/enroll",
        _enroll_payload(enrollment.session, enrollment.raw_secret, pem),
        content_type="application/json",
    ).json()
    device = Device.objects.get(pk=enrolled["device_id"])
    revoke_device(device=device, actor_user=owner_bundle["user"])
    assertion = _assertion(private_key, device.id, "kid-1")
    token_res = client.post(
        "/api/v1/device/token",
        {
            "device_id": str(device.id),
            "public_key_id": "kid-1",
            "client_assertion": assertion,
        },
        content_type="application/json",
    )
    assert token_res.status_code == 401
    heartbeat = client.post(
        "/api/v1/device/heartbeat",
        {"management_active": True},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {enrolled['access_token']}",
    )
    assert heartbeat.status_code in (401, 403)


@pytest.mark.django_db
def test_unauthorized_device_endpoints(client):
    assert client.get("/api/v1/device/me").status_code in (401, 403)
    assert client.post("/api/v1/device/heartbeat", {}, content_type="application/json").status_code in (401, 403)
    parent = client.post(
        "/api/v1/auth/register",
        {"email": "phase2parent@example.com", "password": "CorrectHorseBattery1!"},
        content_type="application/json",
    )
    assert parent.status_code == 201
    # Parent session must not access device-authenticated routes.
    assert client.get("/api/v1/device/me").status_code in (401, 403)
