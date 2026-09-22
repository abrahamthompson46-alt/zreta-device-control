from rest_framework import serializers, status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.mixins import OrganizationAPIMixin
from apps.audit.services import request_meta
from apps.devices.location import (
    latest_location,
    location_history,
    serialize_location,
    set_location_collection,
)
from apps.devices.models import Device, EnrollmentSession, EnrollmentStatus
from apps.devices.services import (
    EnrollmentError,
    cancel_enrollment_session,
    create_enrollment_session,
    rename_device,
    revoke_device,
)


def org_device(organization, device_id) -> Device:
    device = Device.objects.filter(pk=device_id, organization=organization).select_related(
        "status", "status__last_location"
    ).first()
    if device is None:
        raise NotFound("Device not found.")
    return device


class EnrollmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = EnrollmentSession
        fields = (
            "id",
            "status",
            "expires_at",
            "used_at",
            "cancelled_at",
            "allowed_provisioning_modes",
            "created_at",
        )


class DeviceSerializer(serializers.ModelSerializer):
    last_seen_at = serializers.DateTimeField(source="status.last_seen_at", read_only=True)
    connectivity = serializers.CharField(source="status.connectivity", read_only=True)

    class Meta:
        model = Device
        fields = (
            "id",
            "display_name",
            "manufacturer",
            "model",
            "management_mode",
            "android_version",
            "dpc_version",
            "enrolled_at",
            "is_active",
            "last_seen_at",
            "connectivity",
            "created_at",
        )
        read_only_fields = fields


class EnrollmentCreateAPIView(OrganizationAPIMixin, APIView):
    permission_classes = [IsAuthenticated]
    manage_required = True

    def post(self, request):
        modes = request.data.get("allowed_provisioning_modes") or ["device_owner"]
        created = create_enrollment_session(
            organization=self.organization,
            created_by=request.user,
            allowed_provisioning_modes=modes,
            request_meta=request_meta(request),
        )
        data = EnrollmentSerializer(created.session).data
        data["enrollment_secret"] = created.raw_secret
        data["payload"] = created.payload
        return Response(data, status=status.HTTP_201_CREATED)


class EnrollmentDetailAPIView(OrganizationAPIMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, enrollment_id):
        session = EnrollmentSession.objects.filter(
            pk=enrollment_id, organization=self.organization
        ).first()
        if session is None:
            raise NotFound("Enrollment session not found.")
        data = EnrollmentSerializer(session).data
        # Never return the raw secret after creation.
        return Response(data)


class EnrollmentCancelAPIView(OrganizationAPIMixin, APIView):
    permission_classes = [IsAuthenticated]
    manage_required = True

    def post(self, request, enrollment_id):
        session = EnrollmentSession.objects.filter(
            pk=enrollment_id, organization=self.organization
        ).first()
        if session is None:
            raise NotFound("Enrollment session not found.")
        try:
            session = cancel_enrollment_session(
                session=session,
                actor_user=request.user,
                request_meta=request_meta(request),
            )
        except EnrollmentError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(EnrollmentSerializer(session).data)


class DeviceListAPIView(OrganizationAPIMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        devices = Device.objects.filter(organization=self.organization).select_related("status")
        return Response(DeviceSerializer(devices, many=True).data)


class DeviceDetailAPIView(OrganizationAPIMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, device_id):
        return Response(DeviceSerializer(org_device(self.organization, device_id)).data)

    def patch(self, request, device_id):
        if not self.membership.can_manage:
            raise PermissionDenied("This action requires an owner or admin role.")
        device = org_device(self.organization, device_id)
        name = (request.data.get("display_name") or "").strip()
        if not name:
            raise ValidationError({"display_name": "This field is required."})
        try:
            device = rename_device(
                device=device,
                display_name=name,
                actor_user=request.user,
                request_meta=request_meta(request),
            )
        except EnrollmentError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        device = Device.objects.select_related("status").get(pk=device.pk)
        return Response(DeviceSerializer(device).data)


class DeviceRevokeAPIView(OrganizationAPIMixin, APIView):
    permission_classes = [IsAuthenticated]
    manage_required = True

    def post(self, request, device_id):
        device = org_device(self.organization, device_id)
        try:
            device = revoke_device(
                device=device,
                actor_user=request.user,
                request_meta=request_meta(request),
            )
        except EnrollmentError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        device = Device.objects.select_related("status").get(pk=device.pk)
        return Response(DeviceSerializer(device).data)


class DeviceLocationEnableAPIView(OrganizationAPIMixin, APIView):
    permission_classes = [IsAuthenticated]
    manage_required = True

    def post(self, request, device_id):
        device = org_device(self.organization, device_id)
        try:
            device = set_location_collection(
                device=device,
                enabled=True,
                actor_user=request.user,
                request_meta=request_meta(request),
            )
        except EnrollmentError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(
            {
                "device_id": str(device.id),
                "location_collection_enabled": device.location_collection_enabled,
            }
        )


class DeviceLocationDisableAPIView(OrganizationAPIMixin, APIView):
    permission_classes = [IsAuthenticated]
    manage_required = True

    def post(self, request, device_id):
        device = org_device(self.organization, device_id)
        device = set_location_collection(
            device=device,
            enabled=False,
            actor_user=request.user,
            request_meta=request_meta(request),
        )
        return Response(
            {
                "device_id": str(device.id),
                "location_collection_enabled": device.location_collection_enabled,
            }
        )


class DeviceLocationLatestAPIView(OrganizationAPIMixin, APIView):
    permission_classes = [IsAuthenticated]
    manage_required = True

    def get(self, request, device_id):
        device = org_device(self.organization, device_id)
        record = latest_location(device)
        reason = None
        if record is None:
            if not device.location_collection_enabled:
                reason = "not_enabled"
            elif not getattr(device.status, "last_seen_at", None):
                reason = "offline"
            else:
                reason = "no_fix"
        return Response(
            {
                "device_id": str(device.id),
                "location_collection_enabled": device.location_collection_enabled,
                "location": serialize_location(record),
                "reason": reason,
            }
        )


class DeviceLocationHistoryAPIView(OrganizationAPIMixin, APIView):
    permission_classes = [IsAuthenticated]
    manage_required = True

    def get(self, request, device_id):
        from django.utils.dateparse import parse_datetime

        device = org_device(self.organization, device_id)
        since = parse_datetime(request.query_params.get("from") or "") if request.query_params.get("from") else None
        until = parse_datetime(request.query_params.get("to") or "") if request.query_params.get("to") else None
        try:
            limit = int(request.query_params.get("limit") or 200)
        except ValueError:
            limit = 200
        records = location_history(device, since=since, until=until, limit=limit)
        return Response(
            {
                "device_id": str(device.id),
                "results": [serialize_location(record) for record in records],
            }
        )
