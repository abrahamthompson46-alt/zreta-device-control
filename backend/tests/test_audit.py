import pytest

from apps.audit.models import AuditEvent
from apps.audit.services import record_audit


@pytest.mark.django_db
def test_audit_redacts_secrets(owner_bundle):
    record_audit(
        organization=owner_bundle["org"],
        actor_user=owner_bundle["user"],
        action="test.sensitive",
        new_snapshot={
            "password": "should-not-store",
            "enrollment_secret": "raw-secret",
            "display_name": "ok",
            "latitude": 1.23,
        },
    )
    event = AuditEvent.objects.get(action="test.sensitive")
    assert event.new_snapshot["password"] == "[redacted]"
    assert event.new_snapshot["enrollment_secret"] == "[redacted]"
    assert event.new_snapshot["latitude"] == "[redacted]"
    assert event.new_snapshot["display_name"] == "ok"
    assert "should-not-store" not in str(event.new_snapshot)
    assert "raw-secret" not in str(event.new_snapshot)


@pytest.mark.django_db
def test_audit_append_only(owner_bundle):
    event = record_audit(
        organization=owner_bundle["org"],
        actor_user=owner_bundle["user"],
        action="test.append",
    )
    with pytest.raises(ValueError):
        event.result = "tampered"
        event.save()
    with pytest.raises(ValueError):
        event.delete()
