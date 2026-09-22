import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models

from .managers import UserManager


class User(AbstractBaseUser, PermissionsMixin):
    """Email-authenticated parent/admin user.

    MFA is not implemented in Phase 1. `mfa_enabled` is a reserved hook so a
    later authenticator app flow can be added without replacing the user model.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    mfa_enabled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        ordering = ["email"]

    def __str__(self) -> str:
        return self.email


class OrganizationType(models.TextChoices):
    FAMILY = "family", "Family"
    SCHOOL = "school", "School"
    ENTERPRISE = "enterprise", "Enterprise"


class MembershipRole(models.TextChoices):
    OWNER = "owner", "Owner"
    ADMIN = "admin", "Admin"
    VIEWER = "viewer", "Viewer"


MANAGE_ROLES = {MembershipRole.OWNER, MembershipRole.ADMIN}
READ_ROLES = {MembershipRole.OWNER, MembershipRole.ADMIN, MembershipRole.VIEWER}


class Organization(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=150)
    type = models.CharField(
        max_length=20,
        choices=OrganizationType.choices,
        default=OrganizationType.FAMILY,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Membership(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    role = models.CharField(max_length=20, choices=MembershipRole.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "organization"],
                name="uniq_membership_user_organization",
            )
        ]
        ordering = ["organization__name", "user__email"]

    def __str__(self) -> str:
        return f"{self.user} @ {self.organization} ({self.role})"

    @property
    def can_manage(self) -> bool:
        return self.role in MANAGE_ROLES
