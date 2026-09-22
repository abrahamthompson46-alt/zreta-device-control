from __future__ import annotations

import pytest

from apps.audit.models import AuditEvent
from apps.devices.models import Device, ManagementMode
from apps.policies.models import DevicePolicyAssignment, Policy, PolicyVersion, PolicyVersionStatus
from apps.policies.schema import empty_policy_document

pytestmark = pytest.mark.django_db


def _login(client, user, password):
    return client.post("/login/", {"username": user.email, "password": password})


def _create_policy(client, name="School night", description=""):
    return client.post(
        "/api/v1/policies",
        {"name": name, "description": description, "organization_id": "should-be-ignored"},
        content_type="application/json",
    )


@pytest.fixture
def other_device(other_bundle):
    return Device.objects.create(
        organization=other_bundle["org"],
        display_name="Other phone",
        management_mode=ManagementMode.DEVICE_OWNER,
    )


# --- Authentication / authorization ---


def test_unauthenticated_policies_rejected(client):
    assert client.get("/api/v1/policies").status_code in (401, 403)


def test_owner_can_create_and_admin_can_publish(client, owner_bundle, admin_user, password):
    _login(client, owner_bundle["user"], password)
    created = _create_policy(client)
    assert created.status_code == 201
    policy_id = created.json()["id"]
    version_id = created.json()["initial_version"]["id"]

    client.post("/api/v1/auth/logout")
    _login(client, admin_user, password)
    published = client.post(f"/api/v1/policies/{policy_id}/versions/{version_id}/publish")
    assert published.status_code == 200
    assert published.json()["status"] == "published"
    assert published.json()["content_hash"].startswith("sha256:")


def test_viewer_can_read_but_not_mutate(client, viewer_user, owner_bundle, password, device):
    _login(client, owner_bundle["user"], password)
    created = _create_policy(client)
    policy_id = created.json()["id"]
    version_id = created.json()["initial_version"]["id"]
    client.post(f"/api/v1/policies/{policy_id}/versions/{version_id}/publish")

    client.post("/api/v1/auth/logout")
    _login(client, viewer_user, password)
    assert client.get("/api/v1/policies").status_code == 200
    assert client.get(f"/api/v1/policies/{policy_id}").status_code == 200
    assert client.get(f"/api/v1/policies/{policy_id}/versions").status_code == 200
    assert client.get("/api/v1/policies/assignments").status_code == 200

    assert client.post("/api/v1/policies", {"name": "Nope"}, content_type="application/json").status_code == 403
    assert client.patch(
        f"/api/v1/policies/{policy_id}",
        {"name": "Hack"},
        content_type="application/json",
    ).status_code == 403
    assert client.post(f"/api/v1/policies/{policy_id}/versions/{version_id}/publish").status_code == 403
    assert client.post(
        "/api/v1/policies/assignments",
        {"device_id": str(device.id), "policy_id": policy_id},
        content_type="application/json",
    ).status_code == 403


# --- Tenant isolation ---


def test_cross_tenant_policy_get_patch_publish_404(
    client, owner_bundle, other_bundle, password
):
    _login(client, owner_bundle["user"], password)
    created = _create_policy(client)
    policy_id = created.json()["id"]
    version_id = created.json()["initial_version"]["id"]

    client.post("/api/v1/auth/logout")
    _login(client, other_bundle["user"], password)
    assert client.get(f"/api/v1/policies/{policy_id}").status_code == 404
    assert client.patch(
        f"/api/v1/policies/{policy_id}",
        {"name": "Stolen"},
        content_type="application/json",
    ).status_code == 404
    assert client.post(f"/api/v1/policies/{policy_id}/versions/{version_id}/publish").status_code == 404


def test_cross_tenant_assignment_rejected(
    client, owner_bundle, other_bundle, other_device, password, device
):
    _login(client, owner_bundle["user"], password)
    created = _create_policy(client)
    policy_id = created.json()["id"]
    version_id = created.json()["initial_version"]["id"]
    client.post(f"/api/v1/policies/{policy_id}/versions/{version_id}/publish")

    # Other org policy/device
    client.post("/api/v1/auth/logout")
    _login(client, other_bundle["user"], password)
    other_policy = _create_policy(client, name="Other policy")
    other_policy_id = other_policy.json()["id"]

    client.post("/api/v1/auth/logout")
    _login(client, owner_bundle["user"], password)
    assert client.post(
        "/api/v1/policies/assignments",
        {"device_id": str(device.id), "policy_id": other_policy_id},
        content_type="application/json",
    ).status_code == 404
    assert client.post(
        "/api/v1/policies/assignments",
        {"device_id": str(other_device.id), "policy_id": policy_id},
        content_type="application/json",
    ).status_code == 404


def test_cross_tenant_pinned_version_rejected(client, owner_bundle, other_bundle, password, device):
    _login(client, owner_bundle["user"], password)
    created = _create_policy(client, name="A")
    policy_id = created.json()["id"]
    version_id = created.json()["initial_version"]["id"]
    client.post(f"/api/v1/policies/{policy_id}/versions/{version_id}/publish")

    client.post("/api/v1/auth/logout")
    _login(client, other_bundle["user"], password)
    foreign = _create_policy(client, name="B")
    foreign_id = foreign.json()["id"]
    foreign_version = foreign.json()["initial_version"]["id"]
    client.post(f"/api/v1/policies/{foreign_id}/versions/{foreign_version}/publish")

    client.post("/api/v1/auth/logout")
    _login(client, owner_bundle["user"], password)
    response = client.post(
        "/api/v1/policies/assignments",
        {
            "device_id": str(device.id),
            "policy_id": policy_id,
            "pinned_version_id": foreign_version,
        },
        content_type="application/json",
    )
    assert response.status_code == 404


# --- Lifecycle API ---


def test_create_policy_creates_initial_draft(client, owner_bundle, password):
    _login(client, owner_bundle["user"], password)
    response = _create_policy(client, name="Default", description="Desc")
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Default"
    assert body["description"] == "Desc"
    assert body["initial_version"]["status"] == "draft"
    assert body["initial_version"]["version_number"] == 1
    assert Policy.objects.filter(organization=owner_bundle["org"], name="Default").count() == 1
    assert AuditEvent.objects.filter(action="policy.created").exists()
    assert AuditEvent.objects.filter(action="policy.version_created").exists()
    # organization_id in body ignored — policy is under session org
    assert str(Policy.objects.get(pk=body["id"]).organization_id) == str(owner_bundle["org"].id)


def test_list_and_detail_policy(client, owner_bundle, password):
    _login(client, owner_bundle["user"], password)
    created = _create_policy(client)
    policy_id = created.json()["id"]
    listed = client.get("/api/v1/policies")
    assert listed.status_code == 200
    assert any(item["id"] == policy_id for item in listed.json())
    detail = client.get(f"/api/v1/policies/{policy_id}")
    assert detail.status_code == 200
    assert detail.json()["assignment_count"] == 0
    assert detail.json()["current_published_version"] is None


def test_create_edit_publish_rollback_version(client, owner_bundle, password):
    _login(client, owner_bundle["user"], password)
    created = _create_policy(client)
    policy_id = created.json()["id"]
    v1_id = created.json()["initial_version"]["id"]

    published = client.post(f"/api/v1/policies/{policy_id}/versions/{v1_id}/publish")
    assert published.status_code == 200
    assert published.json()["status"] == "published"
    hash1 = published.json()["content_hash"]

    # Historical published cannot be edited
    edit_published = client.patch(
        f"/api/v1/policies/{policy_id}/versions/{v1_id}",
        {"document": empty_policy_document()},
        content_type="application/json",
    )
    assert edit_published.status_code == 400

    # New draft with document change
    v2 = client.post(
        f"/api/v1/policies/{policy_id}/versions",
        {"document": {**empty_policy_document(), "internet": {"disallow_config_wifi": True}}},
        content_type="application/json",
    )
    assert v2.status_code == 201
    v2_id = v2.json()["id"]
    edited = client.patch(
        f"/api/v1/policies/{policy_id}/versions/{v2_id}",
        {"document": {**empty_policy_document(), "internet": {"disallow_config_mobile_networks": True}}},
        content_type="application/json",
    )
    assert edited.status_code == 200
    assert edited.json()["document"]["internet"]["disallow_config_mobile_networks"] is True

    published2 = client.post(f"/api/v1/policies/{policy_id}/versions/{v2_id}/publish")
    assert published2.status_code == 200
    assert PolicyVersion.objects.get(pk=v1_id).status == PolicyVersionStatus.SUPERSEDED

    rollback = client.post(f"/api/v1/policies/{policy_id}/versions/{v1_id}/rollback")
    assert rollback.status_code == 201
    assert rollback.json()["version_number"] == 3
    assert rollback.json()["content_hash"] == hash1
    assert PolicyVersion.objects.get(pk=v1_id).document == empty_policy_document()


def test_invalid_publication_returns_error(client, owner_bundle, password):
    _login(client, owner_bundle["user"], password)
    created = _create_policy(client)
    policy_id = created.json()["id"]
    bad = client.post(
        f"/api/v1/policies/{policy_id}/versions",
        {"document": {"schema_version": 1, "internet": {}}},
        content_type="application/json",
    )
    bad_id = bad.json()["id"]
    response = client.post(f"/api/v1/policies/{policy_id}/versions/{bad_id}/publish")
    assert response.status_code == 400
    assert response.json()["code"] == "missing_keys"
    assert PolicyVersion.objects.get(pk=bad_id).status == "draft"


def test_versions_list_omits_document(client, owner_bundle, password):
    _login(client, owner_bundle["user"], password)
    created = _create_policy(client)
    policy_id = created.json()["id"]
    versions = client.get(f"/api/v1/policies/{policy_id}/versions")
    assert versions.status_code == 200
    assert "document" not in versions.json()[0]


# --- Assignments ---


def test_assignment_crud_and_effective_version(client, owner_bundle, password, device):
    _login(client, owner_bundle["user"], password)
    created = _create_policy(client)
    policy_id = created.json()["id"]
    v1_id = created.json()["initial_version"]["id"]
    # Assignment before publish: allowed, effective_version null
    assigned = client.post(
        "/api/v1/policies/assignments",
        {"device_id": str(device.id), "policy_id": policy_id},
        content_type="application/json",
    )
    assert assigned.status_code == 201
    assert assigned.json()["effective_version"] is None
    assignment_id = assigned.json()["id"]
    assert AuditEvent.objects.filter(action="policy.assigned").exists()

    dup = client.post(
        "/api/v1/policies/assignments",
        {"device_id": str(device.id), "policy_id": policy_id},
        content_type="application/json",
    )
    assert dup.status_code == 409

    client.post(f"/api/v1/policies/{policy_id}/versions/{v1_id}/publish")
    listed = client.get("/api/v1/policies/assignments")
    assert listed.json()[0]["effective_version"]["id"] == v1_id

    # Second policy + pin
    other = _create_policy(client, name="Weekend")
    other_id = other.json()["id"]
    other_v = other.json()["initial_version"]["id"]
    client.post(f"/api/v1/policies/{other_id}/versions/{other_v}/publish")

    patched = client.patch(
        f"/api/v1/policies/assignments/{assignment_id}",
        {"policy_id": other_id, "pinned_version_id": other_v},
        content_type="application/json",
    )
    assert patched.status_code == 200
    assert patched.json()["policy_id"] == other_id
    assert patched.json()["pinned_version_id"] == other_v
    assert patched.json()["effective_version"]["id"] == other_v

    deleted = client.delete(f"/api/v1/policies/assignments/{assignment_id}")
    assert deleted.status_code == 204
    assert not DevicePolicyAssignment.objects.filter(pk=assignment_id).exists()
    assert AuditEvent.objects.filter(action="policy.unassigned").exists()


def test_pinned_version_must_be_published(client, owner_bundle, password, device):
    _login(client, owner_bundle["user"], password)
    created = _create_policy(client)
    policy_id = created.json()["id"]
    draft_id = created.json()["initial_version"]["id"]
    response = client.post(
        "/api/v1/policies/assignments",
        {
            "device_id": str(device.id),
            "policy_id": policy_id,
            "pinned_version_id": draft_id,
        },
        content_type="application/json",
    )
    assert response.status_code == 400
    assert response.json()["code"] == "pinned_not_published"


def test_audit_snapshots_have_no_document(client, owner_bundle, password, device):
    _login(client, owner_bundle["user"], password)
    created = _create_policy(client)
    policy_id = created.json()["id"]
    v1_id = created.json()["initial_version"]["id"]
    client.post(f"/api/v1/policies/{policy_id}/versions/{v1_id}/publish")
    client.post(
        "/api/v1/policies/assignments",
        {"device_id": str(device.id), "policy_id": policy_id},
        content_type="application/json",
    )
    for event in AuditEvent.objects.filter(action__startswith="policy."):
        blob = str(event.new_snapshot) + str(event.old_snapshot)
        assert "internet" not in blob
        assert "document" not in (event.new_snapshot or {})
