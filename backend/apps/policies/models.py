from __future__ import annotations

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class PolicyVersionStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PUBLISHED = "published", "Published"
    SUPERSEDED = "superseded", "Superseded"
    ARCHIVED = "archived", "Archived"


class Policy(models.Model):
    """Organization-scoped named policy container (Phase 4.1 domain foundation)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "accounts.Organization",
        on_delete=models.CASCADE,
        related_name="policies",
    )
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_policies",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    archived_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["organization__name", "name"]
        constraints = [
            # Active (non-archived) names are unique within an organization.
            # Archived rows may reuse a name so a replacement active policy can be created.
            models.UniqueConstraint(
                fields=["organization", "name"],
                condition=models.Q(archived_at__isnull=True),
                name="uniq_active_policy_name_per_org",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.organization_id})"


class PolicyVersion(models.Model):
    """Immutable versioned policy document once published."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    policy = models.ForeignKey(
        Policy,
        on_delete=models.PROTECT,
        related_name="versions",
    )
    organization = models.ForeignKey(
        "accounts.Organization",
        on_delete=models.CASCADE,
        related_name="policy_versions",
    )
    version_number = models.PositiveIntegerField()
    schema_version = models.PositiveIntegerField(default=1)
    document = models.JSONField(default=dict)
    status = models.CharField(
        max_length=20,
        choices=PolicyVersionStatus.choices,
        default=PolicyVersionStatus.DRAFT,
        db_index=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_policy_versions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(blank=True, null=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="published_policy_versions",
    )
    superseded_at = models.DateTimeField(blank=True, null=True)
    content_hash = models.CharField(max_length=128, blank=True, null=True)

    class Meta:
        ordering = ["policy", "-version_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["policy", "version_number"],
                name="uniq_policy_version_number",
            ),
            # At most one published version per policy (PostgreSQL partial unique index).
            models.UniqueConstraint(
                fields=["policy"],
                condition=models.Q(status=PolicyVersionStatus.PUBLISHED),
                name="uniq_one_published_policy_version",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.policy_id} v{self.version_number} ({self.status})"

    def clean(self):
        super().clean()
        if self.policy_id and self.organization_id:
            if self.policy.organization_id != self.organization_id:
                raise ValidationError(
                    {"organization": "PolicyVersion.organization must match policy.organization."}
                )

    def save(self, *args, **kwargs):
        if self.pk:
            previous = (
                PolicyVersion.objects.filter(pk=self.pk)
                .only(
                    "status",
                    "document",
                    "schema_version",
                    "version_number",
                    "content_hash",
                    "policy_id",
                    "organization_id",
                )
                .first()
            )
            # Non-draft versions: document identity is immutable. Status transitions
            # (e.g. published → superseded) remain allowed for lifecycle services.
            if previous is not None and previous.status != PolicyVersionStatus.DRAFT:
                immutable_fields = (
                    "document",
                    "schema_version",
                    "version_number",
                    "content_hash",
                    "policy_id",
                    "organization_id",
                )
                for field in immutable_fields:
                    if getattr(previous, field) != getattr(self, field):
                        raise ValueError("Non-draft policy versions are immutable.")
        self.full_clean()
        return super().save(*args, **kwargs)


class DevicePolicyAssignment(models.Model):
    """Binds one device to one effective policy (org-scoped)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "accounts.Organization",
        on_delete=models.CASCADE,
        related_name="device_policy_assignments",
    )
    device = models.OneToOneField(
        "devices.Device",
        on_delete=models.CASCADE,
        related_name="policy_assignment",
    )
    policy = models.ForeignKey(
        Policy,
        on_delete=models.PROTECT,
        related_name="device_assignments",
    )
    pinned_version = models.ForeignKey(
        PolicyVersion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="pinned_assignments",
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="device_policy_assignments",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-assigned_at"]
        verbose_name = "device policy assignment"
        verbose_name_plural = "device policy assignments"

    def __str__(self) -> str:
        return f"Assignment {self.device_id} → {self.policy_id}"

    def clean(self):
        super().clean()
        errors = {}
        if self.device_id and self.organization_id:
            if self.device.organization_id != self.organization_id:
                errors["organization"] = "Assignment organization must match device.organization."
        if self.policy_id and self.organization_id:
            if self.policy.organization_id != self.organization_id:
                errors["policy"] = "Assignment organization must match policy.organization."
        if self.device_id and self.policy_id:
            if self.device.organization_id != self.policy.organization_id:
                errors["policy"] = "Policy and device must belong to the same organization."
        if self.pinned_version_id:
            pinned = self.pinned_version
            if self.policy_id and pinned.policy_id != self.policy_id:
                errors["pinned_version"] = "Pinned version must belong to the assigned policy."
            if self.organization_id and pinned.organization_id != self.organization_id:
                errors["pinned_version"] = "Pinned version organization must match assignment."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class PolicyScheduleStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"
    FAILED = "failed", "Failed"


class PolicySchedule(models.Model):
    """
    Schedule publishing a draft policy version at activate_at (UTC).
    FCM wake follows publish. Not a device-local bedtime schedule.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "accounts.Organization",
        on_delete=models.CASCADE,
        related_name="policy_schedules",
    )
    policy = models.ForeignKey(Policy, on_delete=models.CASCADE, related_name="schedules")
    version = models.ForeignKey(
        PolicyVersion,
        on_delete=models.CASCADE,
        related_name="schedules",
    )
    activate_at = models.DateTimeField()
    status = models.CharField(
        max_length=20,
        choices=PolicyScheduleStatus.choices,
        default=PolicyScheduleStatus.PENDING,
        db_index=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_policy_schedules",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    last_error = models.CharField(max_length=64, blank=True, null=True)

    class Meta:
        ordering = ["activate_at"]
        indexes = [
            models.Index(fields=["status", "activate_at"], name="pol_sched_status_act_idx"),
        ]

    def __str__(self) -> str:
        return f"Schedule {self.version_id} @ {self.activate_at}"
