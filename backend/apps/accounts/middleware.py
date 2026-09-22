from django.utils.deprecation import MiddlewareMixin

from .authorization import resolve_current_membership


class CurrentOrganizationMiddleware(MiddlewareMixin):
    def process_request(self, request):
        request.membership = None
        request.organization = None
        if getattr(request, "user", None) and request.user.is_authenticated:
            membership = resolve_current_membership(request)
            request.membership = membership
            request.organization = membership.organization if membership else None
