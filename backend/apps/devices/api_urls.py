from django.urls import path

from . import api
from . import device_api

urlpatterns = [
    path("enrollments", api.EnrollmentCreateAPIView.as_view(), name="api-enrollments-create"),
    path("enrollments/<uuid:enrollment_id>", api.EnrollmentDetailAPIView.as_view(), name="api-enrollments-detail"),
    path(
        "enrollments/<uuid:enrollment_id>/cancel",
        api.EnrollmentCancelAPIView.as_view(),
        name="api-enrollments-cancel",
    ),
    path("devices", api.DeviceListAPIView.as_view(), name="api-devices"),
    path("devices/<uuid:device_id>", api.DeviceDetailAPIView.as_view(), name="api-device-detail"),
    path("devices/<uuid:device_id>/revoke", api.DeviceRevokeAPIView.as_view(), name="api-device-revoke"),
    path(
        "devices/<uuid:device_id>/location/enable",
        api.DeviceLocationEnableAPIView.as_view(),
        name="api-device-location-enable",
    ),
    path(
        "devices/<uuid:device_id>/location/disable",
        api.DeviceLocationDisableAPIView.as_view(),
        name="api-device-location-disable",
    ),
    path(
        "devices/<uuid:device_id>/location/latest",
        api.DeviceLocationLatestAPIView.as_view(),
        name="api-device-location-latest",
    ),
    path(
        "devices/<uuid:device_id>/location/history",
        api.DeviceLocationHistoryAPIView.as_view(),
        name="api-device-location-history",
    ),
    path("device/enroll", device_api.DeviceEnrollAPIView.as_view(), name="api-device-enroll"),
    path("device/token", device_api.DeviceTokenAPIView.as_view(), name="api-device-token"),
    path("device/heartbeat", device_api.DeviceHeartbeatAPIView.as_view(), name="api-device-heartbeat"),
    path("device/me", device_api.DeviceMeAPIView.as_view(), name="api-device-me"),
    path("device/location", device_api.DeviceLocationUploadAPIView.as_view(), name="api-device-location"),
    path("device/policy", device_api.DevicePolicyAPIView.as_view(), name="api-device-policy"),
    path("device/policy/ack", device_api.DevicePolicyAckAPIView.as_view(), name="api-device-policy-ack"),
]
