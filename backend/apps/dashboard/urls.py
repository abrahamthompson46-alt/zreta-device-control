from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("devices/", views.DeviceListView.as_view(), name="devices"),
    path("devices/enroll/", views.EnrollDeviceView.as_view(), name="enroll"),
    path(
        "devices/enroll/<uuid:session_id>/cancel/",
        views.CancelEnrollmentView.as_view(),
        name="enrollment_cancel",
    ),
    path("devices/<uuid:device_id>/", views.DeviceDetailView.as_view(), name="device_detail"),
    path("devices/<uuid:device_id>/rename/", views.DeviceRenameView.as_view(), name="device_rename"),
    path("devices/<uuid:device_id>/revoke/", views.DeviceRevokeView.as_view(), name="device_revoke"),
    path(
        "devices/<uuid:device_id>/location/enable/",
        views.DeviceLocationEnableView.as_view(),
        name="device_location_enable",
    ),
    path(
        "devices/<uuid:device_id>/location/disable/",
        views.DeviceLocationDisableView.as_view(),
        name="device_location_disable",
    ),
    path("audit/", views.AuditListView.as_view(), name="audit"),
    path("policies/", views.PolicyListView.as_view(), name="policies"),
    path("policies/create/", views.PolicyCreateView.as_view(), name="policy_create"),
    path("policies/<uuid:policy_id>/", views.PolicyDetailView.as_view(), name="policy_detail"),
    path(
        "policies/<uuid:policy_id>/versions/<uuid:version_id>/publish/",
        views.PolicyPublishView.as_view(),
        name="policy_publish",
    ),
    path(
        "policies/<uuid:policy_id>/assign/",
        views.PolicyAssignView.as_view(),
        name="policy_assign",
    ),
]
