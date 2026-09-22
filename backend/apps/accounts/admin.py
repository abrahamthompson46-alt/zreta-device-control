from django.contrib import admin

from .models import Membership, Organization, User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("email", "is_active", "mfa_enabled", "created_at")
    search_fields = ("email",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "type", "is_active", "created_at")


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "organization", "role")
