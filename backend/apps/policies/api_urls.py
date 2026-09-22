from django.urls import path

from . import api

urlpatterns = [
    # Assignments before policy_id so "assignments" is not captured as a UUID.
    path("policies/assignments", api.AssignmentListCreateAPIView.as_view(), name="api-policy-assignments"),
    path(
        "policies/assignments/<uuid:assignment_id>",
        api.AssignmentDetailAPIView.as_view(),
        name="api-policy-assignment-detail",
    ),
    path("policies", api.PolicyListCreateAPIView.as_view(), name="api-policies"),
    path("policies/<uuid:policy_id>", api.PolicyDetailAPIView.as_view(), name="api-policy-detail"),
    path(
        "policies/<uuid:policy_id>/versions",
        api.PolicyVersionListCreateAPIView.as_view(),
        name="api-policy-versions",
    ),
    path(
        "policies/<uuid:policy_id>/versions/<uuid:version_id>",
        api.PolicyVersionDetailAPIView.as_view(),
        name="api-policy-version-detail",
    ),
    path(
        "policies/<uuid:policy_id>/versions/<uuid:version_id>/publish",
        api.PolicyVersionPublishAPIView.as_view(),
        name="api-policy-version-publish",
    ),
    path(
        "policies/<uuid:policy_id>/versions/<uuid:version_id>/rollback",
        api.PolicyVersionRollbackAPIView.as_view(),
        name="api-policy-version-rollback",
    ),
]
