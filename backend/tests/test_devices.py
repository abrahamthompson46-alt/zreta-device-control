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
    assert b"Phase 1" not in response.content
    assert b"No devices yet." in response.content


@pytest.mark.django_db
def test_owner_can_delete_device_after_name_confirm(client, owner_bundle, device, password):
    from apps.audit.models import AuditEvent
    from apps.devices.services import delete_device

    client.post("/login/", {"username": owner_bundle["user"].email, "password": password})
    wrong = client.post(
        reverse("dashboard:device_delete", args=[device.id]),
        {"confirm_name": "wrong name"},
    )
    assert wrong.status_code == 302
    assert Device.objects.filter(pk=device.id).exists()

    ok = client.post(
        reverse("dashboard:device_delete", args=[device.id]),
        {"confirm_name": device.display_name},
    )
    assert ok.status_code == 302
    assert ok["Location"].endswith("/devices/")
    assert not Device.objects.filter(pk=device.id).exists()
    event = AuditEvent.objects.get(action="device.deleted")
    assert event.target_device_id is None
    assert event.old_snapshot["display_name"] == "Kid phone"
    assert event.old_snapshot["device_id"] == str(device.id)

    leftover = Device.objects.create(
        organization=owner_bundle["org"],
        display_name="Already revoked",
    )
    revoke_device(device=leftover, actor_user=owner_bundle["user"])
    delete_device(device=leftover, actor_user=owner_bundle["user"])
    assert not Device.objects.filter(pk=leftover.id).exists()


@pytest.mark.django_db
def test_viewer_cannot_delete_device(client, viewer_user, device, password):
    client.post("/login/", {"username": viewer_user.email, "password": password})
    response = client.post(
        reverse("dashboard:device_delete", args=[device.id]),
        {"confirm_name": device.display_name},
    )
    assert response.status_code == 403
    assert Device.objects.filter(pk=device.id).exists()


@pytest.mark.django_db
def test_other_org_cannot_delete_device(client, other_bundle, device, password):
    client.post("/login/", {"username": other_bundle["user"].email, "password": password})
    response = client.post(
        reverse("dashboard:device_delete", args=[device.id]),
        {"confirm_name": device.display_name},
    )
    assert response.status_code == 404
    assert Device.objects.filter(pk=device.id).exists()


@pytest.mark.django_db
def test_device_detail_shows_assigned_policy_name(client, owner_bundle, device, password):
    from apps.policies.assignments import assign_policy_to_device, create_policy
    from apps.policies.lifecycle import publish_version

    policy, draft = create_policy(
        organization=owner_bundle["org"],
        name="TECNO KG5j",
        description="",
        actor_user=owner_bundle["user"],
    )
    publish_version(
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
    client.post("/login/", {"username": owner_bundle["user"].email, "password": password})
    page = client.get(reverse("dashboard:device_detail", args=[device.id]))
    assert page.status_code == 200
    assert b"TECNO KG5j" in page.content
    listing = client.get("/devices/")
    assert b"TECNO KG5j" in listing.content
