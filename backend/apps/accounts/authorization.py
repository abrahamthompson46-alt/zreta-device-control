from django.core.exceptions import PermissionDenied

from .models import MANAGE_ROLES, Membership, MembershipRole, Organization

SESSION_ORG_KEY = "current_organization_id"


class OrganizationRequired(Exception):
    pass


def user_memberships(user):
    if not user.is_authenticated:
        return Membership.objects.none()
    return (
        Membership.objects.select_related("organization")
        .filter(user=user, organization__is_active=True)
        .order_by("organization__name")
    )


def get_membership(user, organization_id) -> Membership | None:
    if not user.is_authenticated or organization_id is None:
        return None
    return (
        Membership.objects.select_related("organization")
        .filter(
            user=user,
            organization_id=organization_id,
            organization__is_active=True,
        )
        .first()
    )


def require_membership(user, organization_id) -> Membership:
    membership = get_membership(user, organization_id)
    if membership is None:
        raise PermissionDenied("You do not have access to this organization.")
    return membership


def require_manage(membership: Membership) -> Membership:
    if membership.role not in MANAGE_ROLES:
        raise PermissionDenied("This action requires an owner or admin role.")
    return membership


def require_owner(membership: Membership) -> Membership:
    if membership.role != MembershipRole.OWNER:
        raise PermissionDenied("This action requires an owner role.")
    return membership


def resolve_current_membership(request) -> Membership | None:
    org_id = request.session.get(SESSION_ORG_KEY)
    membership = get_membership(request.user, org_id) if org_id else None
    if membership:
        return membership
    membership = user_memberships(request.user).first()
    if membership:
        request.session[SESSION_ORG_KEY] = str(membership.organization_id)
    return membership


def set_current_organization(request, organization: Organization) -> None:
    require_membership(request.user, organization.id)
    request.session[SESSION_ORG_KEY] = str(organization.id)
