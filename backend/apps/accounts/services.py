from django.db import transaction

from apps.audit.services import record_audit

from .models import Membership, MembershipRole, Organization, OrganizationType, User


@transaction.atomic
def register_family_account(*, email: str, password: str, organization_name: str = "") -> tuple[User, Organization, Membership]:
    user = User.objects.create_user(email=email, password=password)
    organization = Organization.objects.create(
        name=organization_name.strip() or f"{email.split('@')[0]} family",
        type=OrganizationType.FAMILY,
    )
    membership = Membership.objects.create(
        user=user,
        organization=organization,
        role=MembershipRole.OWNER,
    )
    record_audit(
        organization=organization,
        actor_user=user,
        action="user.registered",
        result="success",
        new_snapshot={"email": user.email, "organization_id": str(organization.id)},
    )
    record_audit(
        organization=organization,
        actor_user=user,
        action="organization.created",
        result="success",
        new_snapshot={"name": organization.name, "type": organization.type},
    )
    return user, organization, membership
