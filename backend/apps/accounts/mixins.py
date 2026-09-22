from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied

from .models import MANAGE_ROLES


class OrganizationContextMixin(LoginRequiredMixin):
    """Require an organization membership resolved from the session, never from a guessed URL alone."""

    manage_required = False

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not getattr(request, "membership", None):
            raise PermissionDenied("No organization membership.")
        if self.manage_required and request.membership.role not in MANAGE_ROLES:
            raise PermissionDenied("This action requires an owner or admin role.")
        return super().dispatch(request, *args, **kwargs)


class OrganizationAPIMixin:
    manage_required = False

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        membership = getattr(request, "membership", None)
        if membership is None:
            from rest_framework.exceptions import PermissionDenied as DRFDenied

            raise DRFDenied("No organization membership.")
        if self.manage_required and membership.role not in MANAGE_ROLES:
            from rest_framework.exceptions import PermissionDenied as DRFDenied

            raise DRFDenied("This action requires an owner or admin role.")
        self.membership = membership
        self.organization = membership.organization
