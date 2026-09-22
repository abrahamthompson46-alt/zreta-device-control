import uuid

from django.conf import settings
from django.db import models


class AuditEvent(models.Model):
    """Append-oriented administrative audit record. Do not update or delete in application code."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "accounts.Organization",
        on_delete=models.CASCADE,
        related_name="audit_events",
    )
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    actor_device = models.ForeignKey(
        "devices.Device",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="actor_audit_events",
    )
    target_device = models.ForeignKey(
        "devices.Device",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="target_audit_events",
    )
    action = models.CharField(max_length=64, db_index=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    result = models.CharField(max_length=32, default="success")
    request_id = models.CharField(max_length=64, blank=True, null=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.TextField(blank=True, null=True)
    old_snapshot = models.JSONField(blank=True, null=True)
    new_snapshot = models.JSONField(blank=True, null=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["organization", "-timestamp"]),
            models.Index(fields=["organization", "action"]),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("Audit events are append-only and cannot be updated.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Audit events are append-only and cannot be deleted.")

    def __str__(self) -> str:
        return f"{self.action} ({self.result})"
