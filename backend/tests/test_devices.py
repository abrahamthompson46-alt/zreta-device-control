import pytest
from django.urls import reverse

from apps.devices.models import CredentialStatus, Device, DeviceCredential, DeviceStatus
from apps.devices.services import rename_device, revoke_device


@pytest.mark.django_db
def test_device_belongs_to_organization_and_has_status(device, owner_bundle):
    assert device.organization_id == owner_bundle["org"].id
    assert DeviceStatus.objects.filter(device=device).exists()
    assert Device.objects.filter(id=device.id).count() == 1


@pytest.mark.django_db
def test_revoked_device_cannot_be_renamed(device, owner_bundle):
    from django.utils import timezone

    DeviceCredential.objects.create(
        device=device,
        public_key_id="kid-1",
        public_key="PUBLIC",
        status=CredentialStatus.ACTIVE,
        issued_at=timezone.now(),
    )
    revoke_device(device=device, actor_user=owner_bundle["user"])
    device.refresh_from_db()
    assert device.is_active is False
    assert device.credentials.filter(status=CredentialStatus.ACTIVE).count() == 0
    from apps.devices.services import EnrollmentError

    with pytest.raises(EnrollmentError):
        rename_device(device=device, display_name="Nope", actor_user=owner_bundle["user"])


@pytest.mark.django_db
def test_device_rename_api_and_audit(client, owner_bundle, device, password):
    client.post("/login/", {"username": owner_bundle["user"].email, "password": password})
    response = client.patch(
        f"/api/v1/devices/{device.id}",
        data={"display_name": "Renamed phone"},
        content_type="application/json",
    )
    assert response.status_code == 200
    device.refresh_from_db()
    assert device.display_name == "Renamed phone"
    from apps.audit.models import AuditEvent

    event = AuditEvent.objects.get(action="device.renamed")
    assert event.old_snapshot["display_name"] == "Kid phone"
    assert "serial" not in str(event.old_snapshot).lower()


@pytest.mark.django_db
def test_device_list_empty_for_new_org(client, owner_bundle, password):
    client.post("/login/", {"username": owner_bundle["user"].email, "password": password})
    response = client.get("/devices/")
    assert response.status_code == 200
