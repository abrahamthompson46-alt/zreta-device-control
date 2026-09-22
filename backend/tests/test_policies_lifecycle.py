from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from django.conf import settings
from django.test.utils import override_settings

from apps.audit.models import AuditEvent
from apps.policies.canonical import (
    canonicalize_document,
    content_hash_for_document,
    serialize_canonical_json,
)
from apps.policies.exceptions import PolicyError
from apps.policies.lifecycle import (
    create_draft_version,
    publish_version,
    rollback_to_version,
    update_draft_version,
)
from apps.policies.models import Policy, PolicyVersion, PolicyVersionStatus
from apps.policies.schema import empty_policy_document, validate_policy_document

pytestmark = pytest.mark.django_db


@pytest.fixture
def policy(owner_bundle):
    return Policy.objects.create(
        organization=owner_bundle["org"],
        name="Lifecycle Policy",
        created_by=owner_bundle["user"],
    )


@pytest.fixture
def other_policy(other_bundle):
    return Policy.objects.create(
        organization=other_bundle["org"],
        name="Other Org Policy",
        created_by=other_bundle["user"],
    )


# --- Validation ---


def test_valid_schema_v1_accepted():
    doc = empty_policy_document()
    assert validate_policy_document(doc)["schema_version"] == 1


def test_non_object_rejected():
    with pytest.raises(PolicyError) as exc:
        validate_policy_document([])
    assert exc.value.code == "invalid_document"


def test_missing_schema_version_rejected():
    doc = empty_policy_document()
    del doc["schema_version"]
    with pytest.raises(PolicyError) as exc:
        validate_policy_document(doc)
    assert exc.value.code == "missing_keys"


def test_unsupported_schema_version_rejected():
    doc = empty_policy_document()
    doc["schema_version"] = 99
    with pytest.raises(PolicyError) as exc:
        validate_policy_document(doc)
    assert exc.value.code == "unsupported_schema_version"


def test_missing_required_section_rejected():
    doc = empty_policy_document()
    del doc["internet"]
    with pytest.raises(PolicyError) as exc:
        validate_policy_document(doc)
    assert exc.value.code == "missing_keys"


def test_section_wrong_type_rejected():
    doc = empty_policy_document()
    doc["calls"] = []
    with pytest.raises(PolicyError) as exc:
        validate_policy_document(doc)
    assert exc.value.code == "invalid_section_type"


def test_unknown_top_level_key_rejected():
    doc = empty_policy_document()
    doc["secret_flag"] = True
    with pytest.raises(PolicyError) as exc:
        validate_policy_document(doc)
    assert exc.value.code == "unknown_keys"


@override_settings(POLICY_DOCUMENT_MAX_BYTES=120)
def test_oversized_document_rejected():
    doc = empty_policy_document()
    doc["internet"] = {"pad": "x" * 200}
    with pytest.raises(PolicyError) as exc:
        validate_policy_document(doc)
    assert exc.value.code == "document_too_large"


def test_deterministic_canonicalization():
    left = {"schema_version": 1, "location": {}, "device": {}, "screen_time": {}, "applications": {}, "calls": {}, "internet": {}}
    right = empty_policy_document()
    assert serialize_canonical_json(left) == serialize_canonical_json(right)
    assert canonicalize_document(left) == canonicalize_document(right)


def test_identical_documents_same_hash():
    a = empty_policy_document()
    b = {
        "location": {},
        "device": {},
        "screen_time": {},
        "applications": {},
        "calls": {},
        "internet": {},
        "schema_version": 1,
    }
    assert content_hash_for_document(a) == content_hash_for_document(b)
    assert content_hash_for_document(a).startswith("sha256:")


def test_changed_document_different_hash():
    a = empty_policy_document()
    b = empty_policy_document()
    b["internet"] = {"disallow_config_wifi": True}
    assert content_hash_for_document(a) != content_hash_for_document(b)


def test_applications_and_device_fields_validated():
    doc = empty_policy_document()
    doc["applications"] = {
        "suspend_packages": ["com.example.game"],
        "hide_packages": ["com.example.hidden"],
        "uninstall_blocked_packages": ["com.example.keep"],
    }
    doc["device"] = {
        "camera_disabled": True,
        "screen_capture_disabled": False,
    }
    validated = validate_policy_document(doc)
    assert validated["applications"]["suspend_packages"] == ["com.example.game"]
    assert validated["device"]["camera_disabled"] is True


def test_calls_internet_screen_time_location_fields_validated():
    doc = empty_policy_document()
    doc["calls"] = {"block_outgoing_calls": True, "block_sms": False}
    doc["internet"] = {
        "disallow_config_wifi": True,
        "disallow_config_mobile_networks": True,
        "disallow_config_tethering": False,
        "disallow_config_vpn": True,
    }
    doc["screen_time"] = {
        "bedtime_start": "21:00",
        "bedtime_end": "07:00",
        "bedtime_block_outgoing_calls": True,
        "bedtime_suspend_packages": ["com.example.game"],
    }
    doc["location"] = {"collection_desired": True}
    validated = validate_policy_document(doc)
    assert validated["calls"]["block_outgoing_calls"] is True
    assert validated["internet"]["disallow_config_wifi"] is True
    assert validated["screen_time"]["bedtime_start"] == "21:00"
    assert validated["location"]["collection_desired"] is True


def test_unknown_applications_key_rejected():
    doc = empty_policy_document()
    doc["applications"] = {"mode": "blocklist"}
    with pytest.raises(PolicyError) as exc:
        validate_policy_document(doc)
    assert exc.value.code == "unknown_section_keys"


def test_unknown_internet_key_rejected():
    doc = empty_policy_document()
    doc["internet"] = {"mode": "block"}
    with pytest.raises(PolicyError) as exc:
        validate_policy_document(doc)
    assert exc.value.code == "unknown_section_keys"


def test_screen_time_requires_both_window_ends():
    doc = empty_policy_document()
    doc["screen_time"] = {"bedtime_start": "21:00"}
    with pytest.raises(PolicyError) as exc:
        validate_policy_document(doc)
    assert exc.value.code == "invalid_section_field"


def test_screen_time_equal_start_end_rejected():
    doc = empty_policy_document()
    doc["screen_time"] = {"bedtime_start": "22:00", "bedtime_end": "22:00"}
    with pytest.raises(PolicyError) as exc:
        validate_policy_document(doc)
    assert exc.value.code == "invalid_section_field"


def test_invalid_package_name_rejected():
    doc = empty_policy_document()
    doc["applications"] = {"suspend_packages": ["not a package"]}
    with pytest.raises(PolicyError) as exc:
        validate_policy_document(doc)
    assert exc.value.code == "invalid_package_name"


def test_device_non_bool_rejected():
    doc = empty_policy_document()
    doc["device"] = {"camera_disabled": 1}
    with pytest.raises(PolicyError) as exc:
        validate_policy_document(doc)
    assert exc.value.code == "invalid_section_field"


def test_internet_traffic_valid_and_optional():
    doc = empty_policy_document()
    assert "traffic" not in validate_policy_document(doc)["internet"]
    doc["internet"] = {
        "disallow_config_wifi": True,
        "traffic": {
            "enabled": True,
            "engine": "local_dns_blocklist",
            "blocked_domains": ["Ads.Example.COM.", "ads.example.com", "tracker.net"],
        },
    }
    validated = validate_policy_document(doc)
    traffic = validated["internet"]["traffic"]
    assert traffic["enabled"] is True
    assert traffic["engine"] == "local_dns_blocklist"
    assert traffic["blocked_domains"] == ["ads.example.com", "tracker.net"]


def test_internet_traffic_enabled_false():
    doc = empty_policy_document()
    doc["internet"] = {"traffic": {"enabled": False, "engine": "local_dns_blocklist", "blocked_domains": []}}
    assert validate_policy_document(doc)["internet"]["traffic"]["enabled"] is False


def test_internet_traffic_invalid_engine_rejected():
    doc = empty_policy_document()
    doc["internet"] = {"traffic": {"enabled": True, "engine": "full_tunnel", "blocked_domains": []}}
    with pytest.raises(PolicyError) as exc:
        validate_policy_document(doc)
    assert exc.value.code == "invalid_section_field"


def test_internet_traffic_malformed_domain_rejected():
    doc = empty_policy_document()
    doc["internet"] = {
        "traffic": {
            "enabled": True,
            "engine": "local_dns_blocklist",
            "blocked_domains": ["https://evil.com"],
        }
    }
    with pytest.raises(PolicyError) as exc:
        validate_policy_document(doc)
    assert exc.value.code == "invalid_domain"


def test_internet_traffic_ip_rejected():
    doc = empty_policy_document()
    doc["internet"] = {
        "traffic": {"enabled": True, "engine": "local_dns_blocklist", "blocked_domains": ["1.2.3.4"]}
    }
    with pytest.raises(PolicyError) as exc:
        validate_policy_document(doc)
    assert exc.value.code == "invalid_domain"


def test_internet_traffic_unknown_and_deferred_keys_rejected():
    doc = empty_policy_document()
    doc["internet"] = {"traffic": {"enabled": True, "engine": "local_dns_blocklist", "always_on": False}}
    with pytest.raises(PolicyError) as exc:
        validate_policy_document(doc)
    assert exc.value.code == "unknown_section_keys"
    doc = empty_policy_document()
    doc["internet"] = {"traffic": {"enabled": True, "engine": "local_dns_blocklist", "lockdown": False}}
    with pytest.raises(PolicyError) as exc:
        validate_policy_document(doc)
    assert exc.value.code == "unknown_section_keys"


def test_internet_traffic_excessive_list_rejected():
    from apps.policies.schema import TRAFFIC_MAX_DOMAINS

    doc = empty_policy_document()
    domains = [f"host{i}.example.com" for i in range(TRAFFIC_MAX_DOMAINS + 1)]
    doc["internet"] = {
        "traffic": {"enabled": True, "engine": "local_dns_blocklist", "blocked_domains": domains}
    }
    with pytest.raises(PolicyError) as exc:
        validate_policy_document(doc)
    assert exc.value.code == "invalid_section_field"


# --- Lifecycle ---


def test_draft_creation(policy, owner_bundle):
    version = create_draft_version(
        organization=owner_bundle["org"],
        policy_id=policy.id,
        actor_user=owner_bundle["user"],
    )
    assert version.status == PolicyVersionStatus.DRAFT
    assert version.version_number == 1
    assert version.organization_id == owner_bundle["org"].id


def test_version_number_increments(policy, owner_bundle):
    first = create_draft_version(organization=owner_bundle["org"], policy_id=policy.id)
    second = create_draft_version(organization=owner_bundle["org"], policy_id=policy.id)
    assert first.version_number == 1
    assert second.version_number == 2


def test_draft_editing(policy, owner_bundle):
    version = create_draft_version(organization=owner_bundle["org"], policy_id=policy.id)
    updated = update_draft_version(
        organization=owner_bundle["org"],
        version_id=version.id,
        document=empty_policy_document(),
    )
    assert updated.document["schema_version"] == 1
    assert updated.status == PolicyVersionStatus.DRAFT


def test_published_version_cannot_be_edited(policy, owner_bundle):
    draft = create_draft_version(organization=owner_bundle["org"], policy_id=policy.id)
    published = publish_version(
        organization=owner_bundle["org"],
        version_id=draft.id,
        actor_user=owner_bundle["user"],
    )
    with pytest.raises(PolicyError) as exc:
        update_draft_version(
            organization=owner_bundle["org"],
            version_id=published.id,
            document=empty_policy_document(),
        )
    assert exc.value.code == "not_draft"


def test_superseded_version_cannot_be_edited(policy, owner_bundle):
    first = create_draft_version(organization=owner_bundle["org"], policy_id=policy.id)
    publish_version(organization=owner_bundle["org"], version_id=first.id, actor_user=owner_bundle["user"])
    second = create_draft_version(organization=owner_bundle["org"], policy_id=policy.id)
    publish_version(organization=owner_bundle["org"], version_id=second.id, actor_user=owner_bundle["user"])
    first.refresh_from_db()
    assert first.status == PolicyVersionStatus.SUPERSEDED
    with pytest.raises(PolicyError) as exc:
        update_draft_version(
            organization=owner_bundle["org"],
            version_id=first.id,
            document=empty_policy_document(),
        )
    assert exc.value.code == "not_draft"


def test_successful_publication(policy, owner_bundle):
    draft = create_draft_version(organization=owner_bundle["org"], policy_id=policy.id)
    published = publish_version(
        organization=owner_bundle["org"],
        version_id=draft.id,
        actor_user=owner_bundle["user"],
    )
    assert published.status == PolicyVersionStatus.PUBLISHED
    assert published.published_at is not None
    assert published.published_by_id == owner_bundle["user"].id
    assert published.content_hash == content_hash_for_document(published.document)


def test_previous_published_becomes_superseded(policy, owner_bundle):
    d1 = create_draft_version(organization=owner_bundle["org"], policy_id=policy.id)
    v1 = publish_version(organization=owner_bundle["org"], version_id=d1.id, actor_user=owner_bundle["user"])
    d2 = create_draft_version(organization=owner_bundle["org"], policy_id=policy.id)
    v2 = publish_version(organization=owner_bundle["org"], version_id=d2.id, actor_user=owner_bundle["user"])
    v1.refresh_from_db()
    assert v1.status == PolicyVersionStatus.SUPERSEDED
    assert v1.superseded_at is not None
    assert v2.status == PolicyVersionStatus.PUBLISHED
    assert PolicyVersion.objects.filter(policy=policy, status=PolicyVersionStatus.PUBLISHED).count() == 1


def test_failed_publication_leaves_previous_unchanged(policy, owner_bundle):
    good = create_draft_version(organization=owner_bundle["org"], policy_id=policy.id)
    published = publish_version(
        organization=owner_bundle["org"],
        version_id=good.id,
        actor_user=owner_bundle["user"],
    )
    bad = create_draft_version(
        organization=owner_bundle["org"],
        policy_id=policy.id,
        document={"schema_version": 1, "internet": {}},  # missing sections
    )
    with pytest.raises(PolicyError):
        publish_version(organization=owner_bundle["org"], version_id=bad.id, actor_user=owner_bundle["user"])
    published.refresh_from_db()
    bad.refresh_from_db()
    assert published.status == PolicyVersionStatus.PUBLISHED
    assert bad.status == PolicyVersionStatus.DRAFT
    assert PolicyVersion.objects.filter(policy=policy, status=PolicyVersionStatus.PUBLISHED).count() == 1


def test_publish_non_draft_rejected(policy, owner_bundle):
    draft = create_draft_version(organization=owner_bundle["org"], policy_id=policy.id)
    published = publish_version(organization=owner_bundle["org"], version_id=draft.id, actor_user=owner_bundle["user"])
    with pytest.raises(PolicyError) as exc:
        publish_version(organization=owner_bundle["org"], version_id=published.id, actor_user=owner_bundle["user"])
    assert exc.value.code == "not_draft"


def test_rollback_creates_new_version_without_mutating_history(policy, owner_bundle):
    d1 = create_draft_version(
        organization=owner_bundle["org"],
        policy_id=policy.id,
        document=empty_policy_document(),
    )
    v1 = publish_version(organization=owner_bundle["org"], version_id=d1.id, actor_user=owner_bundle["user"])
    hash_v1 = v1.content_hash
    doc_v1 = dict(v1.document)

    d2 = create_draft_version(organization=owner_bundle["org"], policy_id=policy.id)
    d2_doc = empty_policy_document()
    d2_doc["internet"] = {"disallow_config_wifi": True}
    update_draft_version(organization=owner_bundle["org"], version_id=d2.id, document=d2_doc)
    v2 = publish_version(organization=owner_bundle["org"], version_id=d2.id, actor_user=owner_bundle["user"])

    v3 = rollback_to_version(
        organization=owner_bundle["org"],
        target_version_id=v1.id,
        actor_user=owner_bundle["user"],
    )
    v1.refresh_from_db()
    v2.refresh_from_db()
    assert v3.version_number == 3
    assert v3.status == PolicyVersionStatus.PUBLISHED
    assert v3.content_hash == hash_v1
    assert v3.document == doc_v1
    assert v3.id != v1.id
    assert v1.status == PolicyVersionStatus.SUPERSEDED
    assert v1.document == doc_v1
    assert v1.content_hash == hash_v1
    assert v2.status == PolicyVersionStatus.SUPERSEDED


def test_content_hash_correct_on_publish(policy, owner_bundle):
    draft = create_draft_version(organization=owner_bundle["org"], policy_id=policy.id)
    published = publish_version(organization=owner_bundle["org"], version_id=draft.id, actor_user=owner_bundle["user"])
    assert published.content_hash == content_hash_for_document(canonicalize_document(empty_policy_document()))


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(
    "sqlite" in settings.DATABASES["default"]["ENGINE"],
    reason="requires PostgreSQL row locks",
)
def test_concurrent_publication_consistent(policy, owner_bundle):
    d1 = create_draft_version(organization=owner_bundle["org"], policy_id=policy.id)
    d2 = create_draft_version(organization=owner_bundle["org"], policy_id=policy.id)
    results: list[str] = []

    def worker(version_id):
        from django.db import connection

        try:
            publish_version(
                organization=owner_bundle["org"],
                version_id=version_id,
                actor_user=owner_bundle["user"],
            )
            results.append("ok")
        except PolicyError:
            results.append("fail")
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(worker, [d1.id, d2.id]))

    assert results.count("ok") == 2
    assert PolicyVersion.objects.filter(policy=policy, status=PolicyVersionStatus.PUBLISHED).count() == 1
    numbers = list(PolicyVersion.objects.filter(policy=policy).values_list("version_number", flat=True))
    assert sorted(numbers) == [1, 2]
    published = PolicyVersion.objects.get(policy=policy, status=PolicyVersionStatus.PUBLISHED)
    superseded = PolicyVersion.objects.get(policy=policy, status=PolicyVersionStatus.SUPERSEDED)
    assert published.version_number != superseded.version_number


# --- Organization isolation ---


def test_cross_org_cannot_create_draft(policy, other_bundle):
    with pytest.raises(PolicyError) as exc:
        create_draft_version(organization=other_bundle["org"], policy_id=policy.id)
    assert exc.value.code == "policy_not_found"


def test_cross_org_cannot_edit_or_publish(policy, owner_bundle, other_bundle):
    draft = create_draft_version(organization=owner_bundle["org"], policy_id=policy.id)
    with pytest.raises(PolicyError):
        update_draft_version(
            organization=other_bundle["org"],
            version_id=draft.id,
            document=empty_policy_document(),
        )
    with pytest.raises(PolicyError) as exc:
        publish_version(organization=other_bundle["org"], version_id=draft.id)
    assert exc.value.code == "cross_organization"


def test_cross_org_cannot_rollback(policy, owner_bundle, other_bundle):
    draft = create_draft_version(organization=owner_bundle["org"], policy_id=policy.id)
    published = publish_version(organization=owner_bundle["org"], version_id=draft.id)
    with pytest.raises(PolicyError) as exc:
        rollback_to_version(organization=other_bundle["org"], target_version_id=published.id)
    assert exc.value.code == "version_not_found"


# --- Audit ---


def test_version_created_audit(policy, owner_bundle):
    version = create_draft_version(
        organization=owner_bundle["org"],
        policy_id=policy.id,
        actor_user=owner_bundle["user"],
    )
    event = AuditEvent.objects.get(action="policy.version_created")
    assert event.new_snapshot["version_id"] == str(version.id)
    assert event.new_snapshot["policy_id"] == str(policy.id)
    assert "document" not in (event.new_snapshot or {})
    assert "internet" not in str(event.new_snapshot)


def test_publication_and_supersede_audit(policy, owner_bundle):
    d1 = create_draft_version(organization=owner_bundle["org"], policy_id=policy.id)
    publish_version(organization=owner_bundle["org"], version_id=d1.id, actor_user=owner_bundle["user"])
    d2 = create_draft_version(organization=owner_bundle["org"], policy_id=policy.id)
    publish_version(organization=owner_bundle["org"], version_id=d2.id, actor_user=owner_bundle["user"])

    published_events = list(AuditEvent.objects.filter(action="policy.published").order_by("timestamp"))
    superseded_events = list(AuditEvent.objects.filter(action="policy.superseded"))
    assert len(published_events) == 2
    assert len(superseded_events) == 1
    for event in published_events + superseded_events:
        blob = str(event.new_snapshot) + str(event.old_snapshot)
        assert "internet" not in blob
        assert "document" not in (event.new_snapshot or {})
        assert event.new_snapshot.get("content_hash", "").startswith("sha256:") or event.action == "policy.superseded"
