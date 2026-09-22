def current_organization(request):
    return {
        "current_organization": getattr(request, "organization", None),
        "current_membership": getattr(request, "membership", None),
        "user_memberships": (
            request.user.memberships.select_related("organization")
            if getattr(request, "user", None) and request.user.is_authenticated
            else []
        ),
    }
