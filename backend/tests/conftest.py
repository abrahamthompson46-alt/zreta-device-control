from __future__ import annotations

from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from apps.accounts.models import Membership, MembershipRole, Organization, OrganizationType, User
from apps.accounts.services import register_family_account
from apps.devices.models import Device, ManagementMode


@pytest.fixture
def password() -> str:
    return "CorrectHorseBattery1!"


@pytest.fixture
def owner_bundle(password):
    user, org, membership = register_family_account(
        email="owner@example.com",
        password=password,
        organization_name="Owner Family",
    )
    return {"user": user, "org": org, "membership": membership, "password": password}


@pytest.fixture
def other_bundle(password):
    user, org, membership = register_family_account(
        email="other@example.com",
        password=password,
        organization_name="Other Family",
    )
    return {"user": user, "org": org, "membership": membership, "password": password}


@pytest.fixture
def admin_user(owner_bundle, password):
    user = User.objects.create_user(email="admin@example.com", password=password)
    Membership.objects.create(
        user=user,
        organization=owner_bundle["org"],
        role=MembershipRole.ADMIN,
    )
    return user


@pytest.fixture
def viewer_user(owner_bundle, password):
    user = User.objects.create_user(email="viewer@example.com", password=password)
    Membership.objects.create(
        user=user,
        organization=owner_bundle["org"],
        role=MembershipRole.VIEWER,
    )
    return user


@pytest.fixture
def device(owner_bundle):
    return Device.objects.create(
        organization=owner_bundle["org"],
        display_name="Kid phone",
        management_mode=ManagementMode.DEVICE_OWNER,
    )


def login(client, email, password):
    return client.post("/login/", {"username": email, "password": password})
