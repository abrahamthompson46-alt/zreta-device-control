import uuid

from django.conf import settings
from django.db import models


class ManagementMode(models.TextChoices):
    UNMANAGED = "unmanaged", "Unmanaged"
    DEVICE_OWNER = "device_owner", "Device Owner"
    PROFILE_OWNER = "profile_owner", "Profile Owner"


class EnrollmentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    CONSUMED = "consumed", "Consumed"
    EXPIRED = "expired", "Expired"
    CANCELLED = "cancelled", "Cancelled"


class ProvisioningMode(models.TextChoices):
    DEVICE_OWNER = "device_owner", "Device Owner"
    PROFILE_OWNER = "profile_owner", "Profile Owner"
    LAB_ADB = "lab_adb", "Lab ADB (development only)"


class CredentialStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    ROTATED = "rotated", "Rotated"
    REVOKED = "revoked", "Revoked"


class ConnectivityStatus(models.TextChoices):
    UNKNOWN = "unknown", "Unknown"
    ONLINE = "online", "Online"
    OFFLINE = "offline", "Offline"


class LocationSource(models.TextChoices):
    FUSED = "fused", "Fused"
    GPS = "gps", "GPS"
    NETWORK = "network", "Network"
    UNKNOWN = "unknown", "Unknown"


class Device(models.Model):
    """Managed Android device. `id` is a public identifier, never an authentication secret."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "accounts.Organization",
        on_delete=models.CASCADE,
        related_name="devices",
    )
    display_name = models.CharField(max_length=120)
    manufacturer = models.CharField(max_length=120, blank=True, default="")
    model = models.CharField(max_length=120, blank=True, default="")
    serial_number = models.CharField(max_length=128, blank=True, null=True)
    android_version = models.CharField(max_length=32, blank=True, null=True)
    dpc_version = models.CharField(max_length=32, blank=True, null=True)
    management_mode = models.CharField(
        max_length=32,
        choices=ManagementMode.choices,
        default=ManagementMode.UNMANAGED,
    )
    enrolled_at = models.DateTimeField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    location_collection_enabled = models.BooleanField(default=False)
    location_authorized_at = models.DateTimeField(blank=True, null=True)
    fcm_registration_token = models.CharField(max_length=512, blank=True, null=True)
    fcm_token_updated_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_name"]
        constraints = [
            models.UniqueConstraint(fields=["id"], name="uniq_device_public_id"),
        ]

    def __str__(self) -> str:
        return self.display_name

    @property
    def is_revoked(self) -> bool:
        return not self.is_active


class EnrollmentSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "accounts.Organization",
        on_delete=models.CASCADE,
        related_name="enrollment_sessions",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_enrollment_sessions",
    )
    token_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(blank=True, null=True)
    cancelled_at = models.DateTimeField(blank=True, null=True)
    status = models.CharField(
        max_length=20,
        choices=EnrollmentStatus.choices,
        default=EnrollmentStatus.PENDING,
        db_index=True,
    )
    allowed_provisioning_modes = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Enrollment {self.id} ({self.status})"


class DeviceCredential(models.Model):
    """Public key registered by a device. The private key must never be generated or stored here.

    Phase 2 will create the keypair inside Android Keystore and submit only the public key.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="credentials")
    public_key_id = models.CharField(max_length=128)
    public_key = models.TextField()
    status = models.CharField(
        max_length=20,
        choices=CredentialStatus.choices,
        default=CredentialStatus.ACTIVE,
    )
    issued_at = models.DateTimeField()
    expires_at = models.DateTimeField(blank=True, null=True)
    last_used_at = models.DateTimeField(blank=True, null=True)
    revoked_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["device", "public_key_id"], name="uniq_device_public_key_id"),
        ]

    def __str__(self) -> str:
        return f"{self.public_key_id} ({self.status})"


class DeviceAssertionJti(models.Model):
    """Replay protection for device-signed client assertions. JTIs are unique until expiry."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="assertion_jtis")
    jti = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["jti"], name="uniq_device_assertion_jti"),
        ]

    def __str__(self) -> str:
        return self.jti


class DeviceStatus(models.Model):
    class DnsFilterReportedState(models.TextChoices):
        UNKNOWN = "unknown", "Unknown"
        STOPPED = "stopped", "Stopped"
        RUNNING = "running", "Running"
        CONSENT_REQUIRED = "consent_required", "VPN consent required"
        FAILED = "failed", "Failed"

    device = models.OneToOneField(Device, on_delete=models.CASCADE, related_name="status")
    last_seen_at = models.DateTimeField(blank=True, null=True)
    battery_level = models.PositiveSmallIntegerField(blank=True, null=True)
    app_version = models.CharField(max_length=32, blank=True, null=True)
    management_active = models.BooleanField(default=False)
    connectivity = models.CharField(
        max_length=16,
        choices=ConnectivityStatus.choices,
        default=ConnectivityStatus.UNKNOWN,
    )
    applied_policy_version = models.PositiveIntegerField(blank=True, null=True)
    applied_policy_version_ref = models.ForeignKey(
        "policies.PolicyVersion",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="+",
    )
    policy_applied_at = models.DateTimeField(blank=True, null=True)
    policy_ack_result = models.CharField(max_length=32, blank=True, null=True)
    policy_ack_client_event_id = models.UUIDField(blank=True, null=True)
    policy_last_error = models.CharField(max_length=32, blank=True, null=True)
    dns_filter_state = models.CharField(
        max_length=32,
        choices=DnsFilterReportedState.choices,
        default=DnsFilterReportedState.UNKNOWN,
    )
    dns_filter_error = models.CharField(max_length=64, blank=True, null=True)
    last_location = models.ForeignKey(
        "LocationRecord",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="+",
    )
    location_last_error = models.CharField(max_length=32, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Status for {self.device_id}"


class LocationRecord(models.Model):
    """Append-oriented location fix. Coordinates must never be written to audit snapshots or logs."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "accounts.Organization",
        on_delete=models.CASCADE,
        related_name="location_records",
    )
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="location_records")
    client_event_id = models.UUIDField()
    captured_at = models.DateTimeField()
    received_at = models.DateTimeField(auto_now_add=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    accuracy_m = models.FloatField(blank=True, null=True)
    source = models.CharField(max_length=16, choices=LocationSource.choices, default=LocationSource.UNKNOWN)
    is_mock = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["organization", "-captured_at"], name="loc_org_captured_idx"),
            models.Index(fields=["device", "-captured_at"], name="loc_device_captured_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["device", "client_event_id"],
                name="uniq_device_location_client_event",
            ),
            models.CheckConstraint(
                condition=models.Q(latitude__gte=-90) & models.Q(latitude__lte=90),
                name="location_lat_range",
            ),
            models.CheckConstraint(
                condition=models.Q(longitude__gte=-180) & models.Q(longitude__lte=180),
                name="location_lon_range",
            ),
        ]

    def __str__(self) -> str:
        return f"Location {self.id}"
