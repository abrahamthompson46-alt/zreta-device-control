from __future__ import annotations

from dataclasses import dataclass

from django.db import models
from django.utils import timezone

from apps.audit.services import record_audit
from apps.billing.models import (
    EntitlementOverride,
    OverrideEffect,
    Plan,
    PlanEntitlement,
    Subscription,
    SubscriptionStatus,
)


@dataclass(frozen=True)
class EntitlementDecision:
    allowed: bool
    feature_key: str
    limit: int | None
    source: str


def _active_override(organization, feature):
    """Newest unexpired override wins. Expired rows are ignored, even if created later.

    Precedence is newest-valid, not deny-over-grant. If a grant and a deny are both
    unexpired, the later created_at (then id) decides. A deny wins only when it is
    that newest valid row.
    """
    now = timezone.now()
    return (
        EntitlementOverride.objects.filter(organization=organization, feature=feature)
        .filter(models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=now))
        .order_by("-created_at", "-id")
        .first()
    )


def _period_still_open(period_end) -> bool:
    if period_end is None:
        return True
    return period_end > timezone.now()


def _subscription_grants_plan(subscription: Subscription | None) -> bool:
    """Status and dates decide the effective plan. This does not write subscription.status."""
    if subscription is None or not subscription.plan.is_active:
        return False
    if not _period_still_open(subscription.current_period_end):
        return False
    now = timezone.now()
    if subscription.status == SubscriptionStatus.TRIALING:
        if subscription.trial_ends_at is not None and subscription.trial_ends_at <= now:
            return False
        return True
    return subscription.status == SubscriptionStatus.ACTIVE


def effective_plan(organization) -> Plan | None:
    """Plan used for entitlement checks. Missing or lapsed subscriptions use the default plan."""
    subscription = (
        Subscription.objects.select_related("plan")
        .filter(organization=organization)
        .first()
    )
    if _subscription_grants_plan(subscription):
        return subscription.plan
    return Plan.objects.filter(is_default=True, is_active=True).first()


def require_entitlement(organization, feature_key: str, *, actor_user=None, request_meta: dict | None = None) -> EntitlementDecision:
    """Decide whether an organization may use a feature. Does not change device policy."""
    from apps.billing.models import Feature

    feature = Feature.objects.filter(key=feature_key, is_active=True).first()
    meta = request_meta or {}
    if feature is None:
        decision = EntitlementDecision(False, feature_key, None, "unknown_feature")
        record_audit(
            organization=organization,
            actor_user=actor_user,
            action="entitlement.denied",
            result="failure",
            new_snapshot={"feature_key": feature_key, "source": decision.source},
            **meta,
        )
        return decision

    override = _active_override(organization, feature)
    if override is not None and override.effect == OverrideEffect.DENY:
        decision = EntitlementDecision(False, feature_key, None, "override_deny")
        record_audit(
            organization=organization,
            actor_user=actor_user,
            action="entitlement.denied",
            result="failure",
            new_snapshot={"feature_key": feature_key, "source": decision.source},
            **meta,
        )
        return decision
    if override is not None and override.effect == OverrideEffect.GRANT:
        return EntitlementDecision(True, feature_key, override.limit, "override_grant")

    plan = effective_plan(organization)
    if plan is None:
        decision = EntitlementDecision(False, feature_key, None, "no_plan")
        record_audit(
            organization=organization,
            actor_user=actor_user,
            action="entitlement.denied",
            result="failure",
            new_snapshot={"feature_key": feature_key, "source": decision.source},
            **meta,
        )
        return decision

    entitlement = PlanEntitlement.objects.filter(plan=plan, feature=feature, enabled=True).first()
    if entitlement is None:
        decision = EntitlementDecision(False, feature_key, None, "plan")
        record_audit(
            organization=organization,
            actor_user=actor_user,
            action="entitlement.denied",
            result="failure",
            new_snapshot={"feature_key": feature_key, "plan_code": plan.code, "source": decision.source},
            **meta,
        )
        return decision
    source = "subscription" if _subscription_grants_plan(Subscription.objects.filter(organization=organization).first()) else "default_plan"
    return EntitlementDecision(True, feature_key, entitlement.limit, source)


def record_plan_change(*, organization, actor_user, plan, old_snapshot, new_snapshot, request_meta=None):
    meta = request_meta or {}
    record_audit(
        organization=organization,
        actor_user=actor_user,
        action="plan.changed",
        result="success",
        old_snapshot=old_snapshot,
        new_snapshot=new_snapshot,
        **meta,
    )


def record_subscription_change(*, organization, actor_user, old_snapshot, new_snapshot, request_meta=None):
    meta = request_meta or {}
    record_audit(
        organization=organization,
        actor_user=actor_user,
        action="subscription.changed",
        result="success",
        old_snapshot=old_snapshot,
        new_snapshot=new_snapshot,
        **meta,
    )


def record_payment_status_change(*, organization, actor_user, old_snapshot, new_snapshot, request_meta=None):
    meta = request_meta or {}
    record_audit(
        organization=organization,
        actor_user=actor_user,
        action="payment.status_changed",
        result="success",
        old_snapshot=old_snapshot,
        new_snapshot=new_snapshot,
        **meta,
    )
