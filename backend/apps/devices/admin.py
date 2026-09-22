from django.contrib import admin

from .models import Device, DeviceCredential, DeviceStatus, EnrollmentSession, LocationRecord


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ("display_name", "organization", "management_mode", "is_active")


@admin.register(EnrollmentSession)
class EnrollmentSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "organization", "status", "expires_at")
    readonly_fields = ("token_hash",)


@admin.register(DeviceCredential)
class DeviceCredentialAdmin(admin.ModelAdmin):
    list_display = ("public_key_id", "device", "status")


@admin.register(DeviceStatus)
class DeviceStatusAdmin(admin.ModelAdmin):
    list_display = ("device", "connectivity", "last_seen_at")


@admin.register(LocationRecord)
class LocationRecordAdmin(admin.ModelAdmin):
    list_display = ("id", "device", "captured_at", "source", "is_mock")
    readonly_fields = ("latitude", "longitude", "accuracy_m", "client_event_id")
