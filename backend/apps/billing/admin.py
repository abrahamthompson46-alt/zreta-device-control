from django.contrib import admin

from apps.accounts.models import Membership
from apps.audit.services import record_audit, request_meta
from apps.billing.models import (
    EntitlementOverride,
    Feature,
    Payment,
    Plan,
    PlanEntitlement,
    PlanPrice,
    Subscription,
)
from apps.billing.services import record_payment_status_change, record_plan_change, record_subscription_change


def _staff_organization(user):
    membership = Membership.objects.filter(user=user).select_related("organization").order_by("created_at").first()
    return membership.organization if membership else None


class PlanPriceInline(admin.TabularInline):
    model = PlanPrice
    extra = 0


class PlanEntitlementInline(admin.TabularInline):
    model = PlanEntitlement
    extra = 0
    autocomplete_fields = ("feature",)


@admin.register(Feature)
class FeatureAdmin(admin.ModelAdmin):
    list_display = ("key", "name", "is_active")
    search_fields = ("key", "name")
    list_filter = ("is_active",)


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_default", "is_active")
    search_fields = ("name", "code")
    list_filter = ("is_active", "is_default")
    inlines = (PlanPriceInline, PlanEntitlementInline)
    autocomplete_fields = ()

    def save_model(self, request, obj, form, change):
        old = None
        if change and obj.pk:
            previous = Plan.objects.filter(pk=obj.pk).first()
            if previous is not None:
                old = {"code": previous.code, "name": previous.name, "is_default": previous.is_default, "is_active": previous.is_active}
        super().save_model(request, obj, form, change)
        organization = _staff_organization(request.user)
        if organization is None:
            return
        record_plan_change(
            organization=organization,
            actor_user=request.user,
            plan=obj,
            old_snapshot=old,
            new_snapshot={"code": obj.code, "name": obj.name, "is_default": obj.is_default, "is_active": obj.is_active},
            request_meta=request_meta(request),
        )


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("organization", "plan", "status", "trial_ends_at", "current_period_end")
    list_filter = ("status", "plan")
    search_fields = ("organization__name",)
    raw_id_fields = ("organization",)

    def save_model(self, request, obj, form, change):
        old = None
        if change and obj.pk:
            previous = Subscription.objects.filter(pk=obj.pk).select_related("plan").first()
            if previous is not None:
                old = {"plan": previous.plan.code, "status": previous.status}
        super().save_model(request, obj, form, change)
        record_subscription_change(
            organization=obj.organization,
            actor_user=request.user,
            old_snapshot=old,
            new_snapshot={"plan": obj.plan.code, "status": obj.status},
            request_meta=request_meta(request),
        )


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("provider", "provider_reference", "organization", "status", "currency", "amount_minor")
    list_filter = ("provider", "status", "currency")
    search_fields = ("provider_reference", "organization__name")
    raw_id_fields = ("organization", "subscription")

    def save_model(self, request, obj, form, change):
        old_status = None
        if change and obj.pk:
            previous = Payment.objects.filter(pk=obj.pk).only("status").first()
            old_status = previous.status if previous else None
        super().save_model(request, obj, form, change)
        if old_status != obj.status:
            record_payment_status_change(
                organization=obj.organization,
                actor_user=request.user,
                old_snapshot={"status": old_status, "provider": obj.provider, "provider_reference": obj.provider_reference},
                new_snapshot={"status": obj.status, "provider": obj.provider, "provider_reference": obj.provider_reference},
                request_meta=request_meta(request),
            )


@admin.register(EntitlementOverride)
class EntitlementOverrideAdmin(admin.ModelAdmin):
    list_display = ("organization", "feature", "effect", "expires_at")
    list_filter = ("effect",)
    search_fields = ("organization__name", "feature__key")
    raw_id_fields = ("organization", "created_by")
    autocomplete_fields = ("feature",)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        record_audit(
            organization=obj.organization,
            actor_user=request.user,
            action="entitlement.override_changed",
            result="success",
            new_snapshot={
                "feature_key": obj.feature.key,
                "effect": obj.effect,
                "expires_at": obj.expires_at.isoformat() if obj.expires_at else None,
            },
            **request_meta(request),
        )
