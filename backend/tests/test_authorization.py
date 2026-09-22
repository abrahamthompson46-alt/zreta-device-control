import pytest
from django.urls import reverse

from apps.devices.models import EnrollmentSession
from apps.devices.services import create_enrollment_session


@pytest.mark.django_db
def test_viewer_cannot_create_enrollment(client, viewer_user, password):
    client.post("/login/", {"username": viewer_user.email, "password": password})
    response = client.post(reverse("dashboard:enroll"), {"allowed_provisioning_modes": ["device_owner"]})
    assert response.status_code == 403
    assert EnrollmentSession.objects.count() == 0


@pytest.mark.django_db
def test_admin_can_create_enrollment(client, admin_user, password):
    client.post("/login/", {"username": admin_user.email, "password": password})
    response = client.post(reverse("dashboard:enroll"), {"allowed_provisioning_modes": ["device_owner"]})
    assert response.status_code == 200
    assert EnrollmentSession.objects.count() == 1
    assert b"Waiting for device enrollment" in response.content


@pytest.mark.django_db
def test_cross_tenant_device_list(client, owner_bundle, other_bundle, device, password):
    client.post("/login/", {"username": other_bundle["user"].email, "password": password})
    response = client.get(reverse("dashboard:devices"))
    assert response.status_code == 200
    assert b"Kid phone" not in response.content


@pytest.mark.django_db
def test_cross_tenant_device_detail_404(client, other_bundle, device, password):
    client.post("/login/", {"username": other_bundle["user"].email, "password": password})
    response = client.get(reverse("dashboard:device_detail", args=[device.id]))
    assert response.status_code == 404


@pytest.mark.django_db
def test_cross_tenant_audit_api(client, owner_bundle, other_bundle, password):
    client.post("/login/", {"username": other_bundle["user"].email, "password": password})
    response = client.get("/api/v1/audit-events")
    assert response.status_code == 200
    assert all(item.get("action") != "never-leak" for item in response.json())
    # Other org should not see owner family registration audits
    actions_org_names = response.json()
    from apps.audit.models import AuditEvent

    owner_ids = set(
        AuditEvent.objects.filter(organization=owner_bundle["org"]).values_list("id", flat=True)
    )
    returned_ids = {item["id"] for item in actions_org_names}
    assert owner_ids.isdisjoint(returned_ids)


@pytest.mark.django_db
def test_unauthorized_api_rejected(client):
    assert client.get("/api/v1/devices").status_code in (401, 403)
    assert client.get("/api/v1/audit-events").status_code in (401, 403)


@pytest.mark.django_db
def test_cannot_cancel_other_org_enrollment(client, owner_bundle, other_bundle, password):
    created = create_enrollment_session(
        organization=owner_bundle["org"],
        created_by=owner_bundle["user"],
    )
    client.post("/login/", {"username": other_bundle["user"].email, "password": password})
    response = client.post(f"/api/v1/enrollments/{created.session.id}/cancel")
    assert response.status_code == 404
    created.session.refresh_from_db()
    assert created.session.status == "pending"
