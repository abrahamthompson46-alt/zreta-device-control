import pytest


@pytest.mark.django_db
def test_api_register_login_me_logout(client, password):
    register = client.post(
        "/api/v1/auth/register",
        {"email": "api@example.com", "password": password, "organization_name": "API family"},
        content_type="application/json",
    )
    assert register.status_code == 201
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "api@example.com"
    client.post("/api/v1/auth/logout")
    assert client.get("/api/v1/auth/me").status_code in (401, 403)
    login = client.post(
        "/api/v1/auth/login",
        {"email": "api@example.com", "password": password},
        content_type="application/json",
    )
    assert login.status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 200


@pytest.mark.django_db
def test_enrollment_api_secret_only_on_create(client, owner_bundle, password):
    client.post("/login/", {"username": owner_bundle["user"].email, "password": password})
    created = client.post(
        "/api/v1/enrollments",
        {"allowed_provisioning_modes": ["device_owner"]},
        content_type="application/json",
    )
    assert created.status_code == 201
    body = created.json()
    assert body["enrollment_secret"]
    assert "enrollment_secret" in body["payload"]
    assert "password" not in body["payload"]
    session_id = body["id"]
    fetched = client.get(f"/api/v1/enrollments/{session_id}")
    assert fetched.status_code == 200
    assert "enrollment_secret" not in fetched.json()


@pytest.mark.django_db
def test_viewer_cannot_patch_or_revoke(client, viewer_user, device, password):
    client.post("/login/", {"username": viewer_user.email, "password": password})
    patch = client.patch(
        f"/api/v1/devices/{device.id}",
        {"display_name": "hack"},
        content_type="application/json",
    )
    revoke = client.post(f"/api/v1/devices/{device.id}/revoke")
    assert patch.status_code == 403
    assert revoke.status_code == 403
