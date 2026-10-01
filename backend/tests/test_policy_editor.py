from __future__ import annotations

import pytest
from django.urls import reverse

from apps.policies.editor import document_from_editor_post, policy_summary, requires_publish_confirmation
from apps.policies.exceptions import PolicyError
from apps.policies.models import PolicyVersionStatus
from apps.policies.schema import (
    APPLICATIONS_ALLOWED_KEYS,
    CALLS_ALLOWED_KEYS,
    DEVICE_ALLOWED_KEYS,
    INTERNET_ALLOWED_KEYS,
    LOCATION_ALLOWED_KEYS,
    SCREEN_TIME_ALLOWED_KEYS,
    empty_policy_document,
    validate_policy_document,
)

pytestmark = pytest.mark.django_db


def _login(client, user, password):
    return client.post("/login/", {"username": user.email, "password": password})


def test_empty_editor_post_is_empty_publishable_document():
    document = document_from_editor_post({})
    assert document == empty_policy_document()
    assert validate_policy_document(document) == document
    assert requires_publish_confirmation(document) is False
    assert policy_summary(document) == ["No restrictions. Devices keep normal camera, calls, SMS, and apps."]


def test_editor_emits_only_existing_schema_keys():
    document = document_from_editor_post(
        {
            "suspend_packages": "com.example.game\ncom.example.chat",
            "hide_packages": "com.example.game",
            "uninstall_blocked_packages": "com.example.chat",
            "camera_disabled": "yes",
            "screen_capture_disabled": "yes",
            "block_outgoing_calls": "yes",
            "block_sms": "yes",
            "disallow_config_wifi": "yes",
            "disallow_config_mobile_networks": "yes",
            "disallow_config_tethering": "yes",
            "disallow_config_vpn": "yes",
            "blocked_domains": "Example.COM\nbad.example.com",
            "bedtime_start": "21:00",
            "bedtime_end": "06:00",
            "bedtime_block_outgoing_calls": "yes",
            "bedtime_suspend_packages": "com.example.game",
            "collection_desired": "yes",
        }
    )
    assert set(document["applications"]) <= APPLICATIONS_ALLOWED_KEYS
    assert set(document["device"]) <= DEVICE_ALLOWED_KEYS
    assert set(document["calls"]) <= CALLS_ALLOWED_KEYS
    assert set(document["internet"]) <= INTERNET_ALLOWED_KEYS
    assert set(document["screen_time"]) <= SCREEN_TIME_ALLOWED_KEYS
    assert set(document["location"]) <= LOCATION_ALLOWED_KEYS
    assert document["device"]["camera_disabled"] is True
    assert document["calls"]["block_sms"] is True
    assert document["internet"]["traffic"]["engine"] == "local_dns_blocklist"
    assert document["internet"]["traffic"]["blocked_domains"] == ["bad.example.com", "example.com"]
    assert document["screen_time"]["bedtime_start"] == "21:00"
    assert document["location"]["collection_desired"] is True
    assert "per_number" not in str(document)
    assert requires_publish_confirmation(document) is True


def test_editor_rejects_invalid_package_and_incomplete_bedtime():
    with pytest.raises(PolicyError):
        document_from_editor_post({"suspend_packages": "not a package"})
    with pytest.raises(PolicyError):
        document_from_editor_post({"bedtime_start": "21:00"})


def _create_policy(client):
    created = client.post(reverse("dashboard:policy_create"), {"name": "Home rules", "description": "editor"})
    assert created.status_code == 302
    return created.url.rstrip("/").split("/")[-1]


def test_owner_saves_empty_draft_and_publishes_without_confirmation(client, owner_bundle, password):
    _login(client, owner_bundle["user"], password)
    policy_id = _create_policy(client)
    saved = client.post(reverse("dashboard:policy_draft_save", args=[policy_id]), {"action": "save"})
    assert saved.status_code == 302
    published = client.post(reverse("dashboard:policy_draft_save", args=[policy_id]), {"action": "publish"})
    assert published.status_code == 302
    from apps.policies.models import PolicyVersion

    version = PolicyVersion.objects.get(policy_id=policy_id, status=PolicyVersionStatus.PUBLISHED)
    assert version.document["schema_version"] == 1
    assert version.document["device"] == {}
    detail = client.get(reverse("dashboard:policy_detail", args=[policy_id]))
    assert b"Disable the camera" in detail.content
    assert b"No restrictions" in detail.content


def test_publish_restrictive_draft_requires_confirmation(client, owner_bundle, password):
    _login(client, owner_bundle["user"], password)
    policy_id = _create_policy(client)
    blocked = client.post(
        reverse("dashboard:policy_draft_save", args=[policy_id]),
        {"action": "publish", "camera_disabled": "yes"},
    )
    assert blocked.status_code == 302
    from apps.policies.models import PolicyVersion

    draft = PolicyVersion.objects.get(policy_id=policy_id, status=PolicyVersionStatus.DRAFT)
    assert draft.document["device"]["camera_disabled"] is True
    assert not PolicyVersion.objects.filter(policy_id=policy_id, status=PolicyVersionStatus.PUBLISHED).exists()
    page = client.get(reverse("dashboard:policy_detail", args=[policy_id]))
    assert b"Camera disabled" in page.content
    assert b"Confirm restrictive controls" in page.content
    published = client.post(
        reverse("dashboard:policy_draft_save", args=[policy_id]),
        {"action": "publish", "camera_disabled": "yes", "confirm_restrictive": "yes"},
    )
    assert published.status_code == 302
    version = PolicyVersion.objects.get(policy_id=policy_id, status=PolicyVersionStatus.PUBLISHED)
    assert version.document["device"]["camera_disabled"] is True


def test_viewer_cannot_edit_and_other_org_cannot_see(client, owner_bundle, viewer_user, other_bundle, password):
    _login(client, owner_bundle["user"], password)
    policy_id = _create_policy(client)
    client.post("/api/v1/auth/logout")

    _login(client, viewer_user, password)
    denied = client.post(reverse("dashboard:policy_draft_save", args=[policy_id]), {"action": "save"})
    assert denied.status_code == 403
    page = client.get(reverse("dashboard:policy_detail", args=[policy_id]))
    assert page.status_code == 200
    assert b"Save draft" not in page.content
    assert b"Review" in page.content
    client.post("/api/v1/auth/logout")

    _login(client, other_bundle["user"], password)
    hidden = client.get(reverse("dashboard:policy_detail", args=[policy_id]))
    assert hidden.status_code == 404
    hidden_post = client.post(reverse("dashboard:policy_draft_save", args=[policy_id]), {"action": "publish"})
    assert hidden_post.status_code == 404
