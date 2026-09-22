from datetime import timedelta

import pytest
from django.conf import settings
from django.utils import timezone

from apps.devices.models import EnrollmentSession
from apps.devices.services import (
    EnrollmentError,
    cancel_enrollment_session,
    consume_enrollment_session,
    create_enrollment_session,
)
from apps.devices.tokens import hash_enrollment_secret


@pytest.mark.django_db
def test_token_hashed_not_stored_plaintext(owner_bundle):
    created = create_enrollment_session(
        organization=owner_bundle["org"],
        created_by=owner_bundle["user"],
    )
    session = EnrollmentSession.objects.get(pk=created.session.pk)
    assert created.raw_secret
    assert session.token_hash != created.raw_secret
    assert created.raw_secret not in session.token_hash
    assert session.token_hash == hash_enrollment_secret(created.raw_secret)
    from apps.audit.models import AuditEvent

    blob = str(list(AuditEvent.objects.filter(action="enrollment.created").values()))
    assert created.raw_secret not in blob


@pytest.mark.django_db
def test_valid_token_consumed_once(owner_bundle):
    created = create_enrollment_session(
        organization=owner_bundle["org"],
        created_by=owner_bundle["user"],
    )
    consume_enrollment_session(session_id=created.session.id, raw_secret=created.raw_secret)
    with pytest.raises(EnrollmentError) as exc:
        consume_enrollment_session(session_id=created.session.id, raw_secret=created.raw_secret)
    assert exc.value.code == "used"


@pytest.mark.django_db
def test_expired_token_rejected(owner_bundle):
    created = create_enrollment_session(
        organization=owner_bundle["org"],
        created_by=owner_bundle["user"],
    )
    EnrollmentSession.objects.filter(pk=created.session.pk).update(
        expires_at=timezone.now() - timedelta(minutes=1)
    )
    with pytest.raises(EnrollmentError) as exc:
        consume_enrollment_session(session_id=created.session.id, raw_secret=created.raw_secret)
    assert exc.value.code == "expired"


@pytest.mark.django_db
def test_cancelled_token_rejected(owner_bundle):
    created = create_enrollment_session(
        organization=owner_bundle["org"],
        created_by=owner_bundle["user"],
    )
    cancel_enrollment_session(session=created.session, actor_user=owner_bundle["user"])
    with pytest.raises(EnrollmentError) as exc:
        consume_enrollment_session(session_id=created.session.id, raw_secret=created.raw_secret)
    assert exc.value.code == "cancelled"


@pytest.mark.django_db
def test_wrong_secret_rejected(owner_bundle):
    created = create_enrollment_session(
        organization=owner_bundle["org"],
        created_by=owner_bundle["user"],
    )
    with pytest.raises(EnrollmentError):
        consume_enrollment_session(session_id=created.session.id, raw_secret="not-the-secret")
    created.session.refresh_from_db()
    assert created.session.status == "pending"


@pytest.mark.django_db
def test_token_bound_to_organization(owner_bundle, other_bundle):
    created = create_enrollment_session(
        organization=owner_bundle["org"],
        created_by=owner_bundle["user"],
    )
    with pytest.raises(EnrollmentError) as exc:
        consume_enrollment_session(
            session_id=created.session.id,
            raw_secret=created.raw_secret,
            organization=other_bundle["org"],
        )
    assert exc.value.code == "wrong_org"


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(
    "sqlite" in settings.DATABASES["default"]["ENGINE"],
    reason="requires PostgreSQL row locks",
)
def test_token_cannot_be_consumed_twice_concurrently(owner_bundle):
    import threading
    from django.db import connection
    created = create_enrollment_session(
        organization=owner_bundle["org"],
        created_by=owner_bundle["user"],
    )
    results: list[str] = []

    def worker():
        from django.db import connection

        try:
            consume_enrollment_session(session_id=created.session.id, raw_secret=created.raw_secret)
            results.append("ok")
        except EnrollmentError:
            results.append("fail")
        finally:
            connection.close()

    threads = [threading.Thread(target=worker), threading.Thread(target=worker)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results.count("ok") == 1
    assert results.count("fail") == 1
    created.session.refresh_from_db()
    assert created.session.status == "consumed"
