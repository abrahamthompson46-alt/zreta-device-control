import pytest
from django.urls import reverse

from apps.accounts.models import Membership, MembershipRole, Organization, User
from apps.audit.models import AuditEvent


@pytest.mark.django_db
def test_registration_creates_family_org_and_owner(client, password):
    response = client.post(
        reverse("accounts:register"),
        {
            "email": "parent@example.com",
            "password1": password,
            "password2": password,
            "organization_name": "Patel family",
        },
    )
    assert response.status_code == 302
    user = User.objects.get(email="parent@example.com")
    membership = Membership.objects.get(user=user)
    assert membership.role == MembershipRole.OWNER
    assert membership.organization.type == "family"
    assert membership.organization.name == "Patel family"
    assert AuditEvent.objects.filter(action="user.registered", organization=membership.organization).exists()
    assert AuditEvent.objects.filter(action="organization.created").exists()


@pytest.mark.django_db
def test_duplicate_email_rejected(client, owner_bundle, password):
    response = client.post(
        reverse("accounts:register"),
        {
            "email": "owner@example.com",
            "password1": password,
            "password2": password,
        },
    )
    assert response.status_code == 200
    assert User.objects.filter(email="owner@example.com").count() == 1


@pytest.mark.django_db
def test_login_success_and_failure(client, owner_bundle, password):
    bad = client.post("/login/", {"username": "owner@example.com", "password": "wrong-password-0"})
    assert bad.status_code == 200
    assert AuditEvent.objects.filter(action="user.login", result="failure").exists()
    good = client.post("/login/", {"username": "owner@example.com", "password": password})
    assert good.status_code == 302
    assert AuditEvent.objects.filter(action="user.login", result="success").exists()


@pytest.mark.django_db
def test_logout(client, owner_bundle, password):
    client.post("/login/", {"username": "owner@example.com", "password": password})
    response = client.post("/logout/")
    assert response.status_code in (200, 302)
    home = client.get("/")
    assert home.status_code == 302


@pytest.mark.django_db
def test_multiple_organizations_supported(owner_bundle):
    second = Organization.objects.create(name="School", type="school")
    Membership.objects.create(
        user=owner_bundle["user"],
        organization=second,
        role=MembershipRole.ADMIN,
    )
    assert owner_bundle["user"].memberships.count() == 2
