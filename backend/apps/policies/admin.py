from django.contrib import admin

from .models import DevicePolicyAssignment, Policy, PolicySchedule, PolicyVersion


@admin.register(Policy)
class PolicyAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "archived_at", "created_at", "updated_at")
    list_filter = ("organization",)
    search_fields = ("name", "description")
    readonly_fields = ("id", "created_at", "updated_at")
    raw_id_fields = ("organization", "created_by")


@admin.register(PolicyVersion)
class PolicyVersionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "policy",
        "organization",
        "version_number",
        "schema_version",
        "status",
        "published_at",
        "created_at",
    )
    list_filter = ("status", "schema_version", "organization")
    search_fields = ("content_hash",)
    readonly_fields = (
        "id",
        "created_at",
        "document",
        "content_hash",
        "version_number",
        "schema_version",
        "status",
        "published_at",
        "superseded_at",
    )
    raw_id_fields = ("policy", "organization", "created_by", "published_by")


@admin.register(DevicePolicyAssignment)
class DevicePolicyAssignmentAdmin(admin.ModelAdmin):
    list_display = ("device", "policy", "organization", "pinned_version", "assigned_at")
    list_filter = ("organization",)
    readonly_fields = ("id", "assigned_at", "updated_at")
    raw_id_fields = ("organization", "device", "policy", "pinned_version", "assigned_by")


@admin.register(PolicySchedule)
class PolicyScheduleAdmin(admin.ModelAdmin):
    list_display = ("id", "policy", "version", "activate_at", "status", "organization", "created_at")
    list_filter = ("status", "organization")
    readonly_fields = ("id", "created_at", "completed_at", "last_error")
    raw_id_fields = ("organization", "policy", "version", "created_by")
