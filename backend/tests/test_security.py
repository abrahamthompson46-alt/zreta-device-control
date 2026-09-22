import pytest
from django.test import Client


def _csrf_token(client: Client, path: str) -> str:
    response = client.get(path)
    return str(response.context["csrf_token"])


@pytest.mark.django_db
def test_csrf_rejects_login_without_token():
    client = Client(enforce_csrf_checks=True)
    response = client.post("/login/", {"username": "owner@example.com", "password": "x"})
    assert response.status_code == 403


@pytest.mark.django_db
def test_csrf_login_with_token_works(owner_bundle, password):
    client = Client(enforce_csrf_checks=True)
    token = _csrf_token(client, "/login/")
    response = client.post(
        "/login/",
        {
            "username": "owner@example.com",
            "password": password,
            "csrfmiddlewaretoken": token,
        },
    )
    assert response.status_code == 302


@pytest.mark.django_db
def test_enrollment_web_requires_csrf(owner_bundle, password):
    client = Client(enforce_csrf_checks=True)
    login_token = _csrf_token(client, "/login/")
    client.post(
        "/login/",
        {
            "username": "owner@example.com",
            "password": password,
            "csrfmiddlewaretoken": login_token,
        },
    )
    response = client.post("/devices/enroll/", {"allowed_provisioning_modes": ["device_owner"]})
    assert response.status_code == 403
