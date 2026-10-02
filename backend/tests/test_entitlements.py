from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.billing.catalog import FEATURE_CATALOG
from apps.billing.models import EntitlementOverride, Feature, OverrideEffect, Payment, Plan, Subscription, SubscriptionStatus
from apps.billing.providers import PaymentProviderError, get_provider, record_payment_status
from apps.billing.services import require_entitlement
from apps.devices.services import create_enrollment_session

pytestmark = pytest.mark.django_db


def test_existing_organization_uses_default_plan_features(owner_bundle):
    decision = require_entitlement(owner_bundle["org"], "device.enroll")
    assert decision.allowed is True
    assert decision.source in {"subscription", "default_plan"}
    for key, _name, _description in FEATURE_CATALOG:
        assert require_entitlement(owner_bundle["org"], key).allowed is True


def test_unknown_feature_is_denied_and_audited(owner_bundle):
    decision = require_entitlement(owner_bundle["org"], "not.a.real.feature")
    assert decision.allowed is False
    assert AuditEvent.objects.filter(action="entitlement.denied", organization=owner_bundle["org"]).exists()


def test_lapsed_subscription_falls_back_to_default_without_touching_devices(owner_bundle):
    paid = Plan.objects.create(code="family-plus", name="Family Plus", is_default=False, is_active=True)
    feature = Feature.objects.get(key="inventory.read")
    paid.entitlements.create(feature=feature, enabled=True, limit=5)
    subscription = Subscription.objects.get(organization=owner_bundle["org"])
    subscription.plan = paid
    subscription.status = SubscriptionStatus.EXPIRED
    subscription.save(update_fields=["plan", "status", "updated_at"])
    decision = require_entitlement(owner_bundle["org"], "device.enroll")
    assert decision.allowed is True
    assert decision.source == "default_plan"


def test_override_deny_and_expired_grant(owner_bundle):
    feature = Feature.objects.get(key="location.history")
    EntitlementOverride.objects.create(
        organization=owner_bundle["org"],
        feature=feature,
        effect=OverrideEffect.DENY,
        expires_at=timezone.now() + timedelta(days=1),
    )
    denied = require_entitlement(owner_bundle["org"], "location.history")
    assert denied.allowed is False
    EntitlementOverride.objects.filter(organization=owner_bundle["org"]).update(
        expires_at=timezone.now() - timedelta(minutes=1)
    )
    restored = require_entitlement(owner_bundle["org"], "location.history")
    assert restored.allowed is True


def test_payment_provider_is_not_live(owner_bundle):
    with pytest.raises(PaymentProviderError):
        get_provider("manual").start_checkout(
            organization=owner_bundle["org"],
            subscription=Subscription.objects.get(organization=owner_bundle["org"]),
            amount_minor=1000,
            currency="GHS",
        )
    with pytest.raises(PaymentProviderError):
        get_provider("paystack")
    payment = Payment.objects.create(
        organization=owner_bundle["org"],
        provider="manual",
        provider_reference="momo-ref-1",
        currency="GHS",
        amount_minor=1500,
    )
    record_payment_status(payment=payment, status="succeeded", actor_user=owner_bundle["user"])
    payment.refresh_from_db()
    assert payment.status == "succeeded"
    assert payment.amount_minor == 1500
    assert AuditEvent.objects.filter(action="payment.status_changed", organization=owner_bundle["org"]).exists()


def test_enrollment_still_creates_session(owner_bundle):
    created = create_enrollment_session(organization=owner_bundle["org"], created_by=owner_bundle["user"])
    assert created.session.organization_id == owner_bundle["org"].id
    assert created.payload["enrollment_secret"]


def _premium_subscription(owner_bundle, *, status, period_end=None, trial_ends_at=None):
    feature = Feature.objects.create(key="premium.extra", name="Premium extra")
    paid = Plan.objects.create(code="family-plus", name="Family Plus", is_default=False, is_active=True)
    paid.entitlements.create(feature=feature, enabled=True, limit=5)
    subscription = Subscription.objects.get(organization=owner_bundle["org"])
    subscription.plan = paid
    subscription.status = status
    subscription.current_period_end = period_end
    subscription.trial_ends_at = trial_ends_at
    subscription.save()
    return feature, subscription


def test_active_period_end_states_do_not_rewrite_status(owner_bundle):
    feature, subscription = _premium_subscription(
        owner_bundle,
        status=SubscriptionStatus.ACTIVE,
        period_end=timezone.now() + timedelta(days=10),
    )
    future = require_entitlement(owner_bundle["org"], feature.key)
    assert future.allowed is True
    assert future.source == "subscription"
    assert future.limit == 5

    subscription.current_period_end = None
    subscription.save(update_fields=["current_period_end", "updated_at"])
    open_ended = require_entitlement(owner_bundle["org"], feature.key)
    assert open_ended.allowed is True
    assert open_ended.source == "subscription"

    subscription.current_period_end = timezone.now() - timedelta(minutes=1)
    subscription.save(update_fields=["current_period_end", "updated_at"])
    elapsed = require_entitlement(owner_bundle["org"], feature.key)
    assert elapsed.allowed is False
    assert elapsed.source == "plan"
    subscription.refresh_from_db()
    assert subscription.status == SubscriptionStatus.ACTIVE


def test_trial_expiration_falls_back_without_status_write(owner_bundle):
    feature, subscription = _premium_subscription(
        owner_bundle,
        status=SubscriptionStatus.TRIALING,
        trial_ends_at=timezone.now() - timedelta(minutes=1),
        period_end=timezone.now() + timedelta(days=3),
    )
    decision = require_entitlement(owner_bundle["org"], feature.key)
    assert decision.allowed is False
    subscription.refresh_from_db()
    assert subscription.status == SubscriptionStatus.TRIALING


def test_override_precedence(owner_bundle):
    feature = Feature.objects.create(key="premium.extra", name="Premium extra")
    org = owner_bundle["org"]
    now = timezone.now()

    grant = EntitlementOverride.objects.create(organization=org, feature=feature, effect=OverrideEffect.GRANT, limit=2)
    allowed = require_entitlement(org, feature.key)
    assert allowed.allowed is True
    assert allowed.source == "override_grant"
    assert allowed.limit == 2

    EntitlementOverride.objects.filter(pk=grant.pk).update(created_at=now - timedelta(days=3))
    deny = EntitlementOverride.objects.create(
        organization=org,
        feature=feature,
        effect=OverrideEffect.DENY,
        expires_at=now + timedelta(days=1),
    )
    EntitlementOverride.objects.filter(pk=deny.pk).update(created_at=now - timedelta(days=1))
    denied = require_entitlement(org, feature.key)
    assert denied.allowed is False
    assert denied.source == "override_deny"

    EntitlementOverride.objects.filter(pk=deny.pk).update(expires_at=now - timedelta(minutes=5))
    restored = require_entitlement(org, feature.key)
    assert restored.allowed is True
    assert restored.source == "override_grant"

    newer_grant = EntitlementOverride.objects.create(organization=org, feature=feature, effect=OverrideEffect.GRANT, limit=9)
    EntitlementOverride.objects.filter(pk=newer_grant.pk).update(created_at=now)
    newest = require_entitlement(org, feature.key)
    assert newest.allowed is True
    assert newest.limit == 9

    EntitlementOverride.objects.filter(organization=org, feature=feature).update(expires_at=now - timedelta(days=1))
    baseline = require_entitlement(org, feature.key)
    assert baseline.allowed is False
    assert baseline.source == "plan"
