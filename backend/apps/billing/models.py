import uuid

from django.conf import settings
from django.db import models


class SubscriptionStatus(models.TextChoices):
    TRIALING = "trialing", "Trialing"
    ACTIVE = "active", "Active"
    PAST_DUE = "past_due", "Past due"
    CANCELED = "canceled", "Canceled"
    EXPIRED = "expired", "Expired"


class BillingInterval(models.TextChoices):
    MONTH = "month", "Month"
    YEAR = "year", "Year"
    NONE = "none", "None"


class PaymentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    CANCELED = "canceled", "Canceled"


class OverrideEffect(models.TextChoices):
    GRANT = "grant", "Grant"
    DENY = "deny", "Deny"


class Feature(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["key"]

    def __str__(self) -> str:
        return self.key


class Plan(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["is_default"],
                condition=models.Q(is_default=True),
                name="uniq_one_default_plan",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class PlanPrice(models.Model):
    """Price in integer minor currency units. GHS pesewas, not a float."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="prices")
    currency = models.CharField(max_length=3, default="GHS")
    amount_minor = models.PositiveIntegerField(default=0)
    interval = models.CharField(max_length=16, choices=BillingInterval.choices, default=BillingInterval.MONTH)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["currency", "interval"]
        constraints = [
            models.UniqueConstraint(
                fields=["plan", "currency", "interval"],
                name="uniq_plan_price_currency_interval",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.plan.code} {self.amount_minor} {self.currency}/{self.interval}"


class PlanEntitlement(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="entitlements")
    feature = models.ForeignKey(Feature, on_delete=models.PROTECT, related_name="plan_entitlements")
    enabled = models.BooleanField(default=True)
    # Null means no numeric cap. Zero means the feature is included with a limit of zero.
    limit = models.PositiveIntegerField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["feature__key"]
        constraints = [
            models.UniqueConstraint(fields=["plan", "feature"], name="uniq_plan_feature"),
        ]

    def __str__(self) -> str:
        return f"{self.plan.code}:{self.feature.key}"


class Subscription(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.OneToOneField(
        "accounts.Organization",
        on_delete=models.CASCADE,
        related_name="subscription",
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")
    status = models.CharField(
        max_length=20,
        choices=SubscriptionStatus.choices,
        default=SubscriptionStatus.ACTIVE,
        db_index=True,
    )
    trial_ends_at = models.DateTimeField(blank=True, null=True)
    current_period_end = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["organization__name"]

    def __str__(self) -> str:
        return f"{self.organization_id} {self.plan.code} ({self.status})"


class Payment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "accounts.Organization",
        on_delete=models.CASCADE,
        related_name="payments",
    )
    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments",
    )
    provider = models.CharField(max_length=32)
    provider_reference = models.CharField(max_length=128)
    status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.PENDING)
    currency = models.CharField(max_length=3, default="GHS")
    amount_minor = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "provider_reference"],
                name="uniq_payment_provider_reference",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.provider}:{self.provider_reference} ({self.status})"


class EntitlementOverride(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "accounts.Organization",
        on_delete=models.CASCADE,
        related_name="entitlement_overrides",
    )
    feature = models.ForeignKey(Feature, on_delete=models.CASCADE, related_name="overrides")
    effect = models.CharField(max_length=8, choices=OverrideEffect.choices)
    limit = models.PositiveIntegerField(blank=True, null=True)
    reason = models.CharField(max_length=200, blank=True, default="")
    expires_at = models.DateTimeField(blank=True, null=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entitlement_overrides",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.organization_id} {self.feature.key} {self.effect}"
