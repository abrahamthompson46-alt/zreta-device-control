from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.services import record_audit, request_meta
from apps.devices.authentication import DeviceJWTAuthentication, IsEnrolledDevice
from apps.devices.crypto import DeviceAuthError
from apps.devices.enrollment import enroll_android_device, issue_token_for_assertion, record_heartbeat
from apps.devices.location import LocationError, ingest_locations
from apps.devices.models import EnrollmentSession
from apps.devices.services import EnrollmentError


def _token_response(device, credential, access_token, ttl):
    return {
        "device_id": str(device.id),
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": ttl,
        "public_key_id": credential.public_key_id,
        "organization_id": str(device.organization_id),
    }


class DeviceEnrollAPIView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data
        try:
            device, credential, access_token, ttl = enroll_android_device(
                session_id=data.get("enrollment_session_id"),
                raw_secret=data.get("enrollment_secret") or "",
                public_key_id=data.get("public_key_id") or "",
                public_key_pem=data.get("public_key") or "",
                disclosure_accepted=bool(data.get("disclosure_accepted")),
                management_mode=data.get("management_mode") or "device_owner",
                display_name=data.get("display_name") or "",
                manufacturer=data.get("manufacturer") or "",
                model=data.get("model") or "",
                android_version=data.get("android_version"),
                dpc_version=data.get("dpc_version"),
                request_meta=request_meta(request),
            )
        except EnrollmentError as exc:
            session = None
            raw_id = data.get("enrollment_session_id")
            try:
                import uuid as uuid_mod

                session = EnrollmentSession.objects.select_related("organization").filter(
                    pk=uuid_mod.UUID(str(raw_id))
                ).first()
            except (ValueError, TypeError):
                session = None
            if session is not None:
                record_audit(
                    organization=session.organization,
                    action="enrollment.device_failed",
                    result="failure",
                    new_snapshot={"enrollment_session_id": str(session.id), "code": exc.code},
                    **request_meta(request),
                )
            return Response({"detail": str(exc), "code": exc.code}, status=status.HTTP_400_BAD_REQUEST)
        body = _token_response(device, credential, access_token, ttl)
        body["management_mode"] = device.management_mode
        return Response(body, status=status.HTTP_201_CREATED)


class DeviceTokenAPIView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data
        try:
            device, credential, access_token, ttl = issue_token_for_assertion(
                device_id=data.get("device_id"),
                public_key_id=data.get("public_key_id") or "",
                client_assertion=data.get("client_assertion") or "",
            )
        except DeviceAuthError as exc:
            return Response({"detail": str(exc), "code": exc.code}, status=status.HTTP_401_UNAUTHORIZED)
        return Response(_token_response(device, credential, access_token, ttl))


class DeviceHeartbeatAPIView(APIView):
    authentication_classes = [DeviceJWTAuthentication]
    permission_classes = [IsEnrolledDevice]

    def post(self, request):
        data = request.data
        try:
            device = record_heartbeat(
                device=request.user.device,
                app_version=data.get("app_version"),
                android_version=data.get("android_version"),
                manufacturer=data.get("manufacturer"),
                model=data.get("model"),
                management_active=bool(data.get("management_active")),
                management_mode=data.get("management_mode"),
                connectivity=data.get("connectivity"),
                battery_level=data.get("battery_level"),
                dpc_version=data.get("dpc_version"),
                dns_filter_state=data.get("dns_filter_state"),
                dns_filter_error=data.get("dns_filter_error"),
            )
        except DeviceAuthError as exc:
            return Response({"detail": str(exc), "code": exc.code}, status=status.HTTP_401_UNAUTHORIZED)
        st = device.status
        from apps.policies.device_policy import get_device_effective_policy

        effective = get_device_effective_policy(device=device)
        return Response(
            {
                "device_id": str(device.id),
                "last_seen_at": st.last_seen_at,
                "management_active": st.management_active,
                "connectivity": st.connectivity,
                "location_collection_enabled": device.location_collection_enabled,
                "policy_version_number": effective.get("version_number"),
                "policy_assignment_state": effective.get("assignment_state"),
                "dns_filter_state": st.dns_filter_state,
                "dns_filter_error": st.dns_filter_error,
            }
        )


class DeviceMeAPIView(APIView):
    authentication_classes = [DeviceJWTAuthentication]
    permission_classes = [IsEnrolledDevice]

    def get(self, request):
        device = request.user.device
        credential = request.user.credential
        st = getattr(device, "status", None)
        from apps.policies.device_policy import get_device_effective_policy

        effective = get_device_effective_policy(device=device)
        return Response(
            {
                "id": str(device.id),
                "display_name": device.display_name,
                "organization_id": str(device.organization_id),
                "management_mode": device.management_mode,
                "is_active": device.is_active,
                "enrolled_at": device.enrolled_at,
                "credential_status": credential.status if credential else None,
                "public_key_id": credential.public_key_id if credential else None,
                "last_seen_at": st.last_seen_at if st else None,
                "management_active": st.management_active if st else False,
                "connectivity": st.connectivity if st else None,
                "dpc_version": device.dpc_version,
                "android_version": device.android_version,
                "location_collection_enabled": device.location_collection_enabled,
                "policy_version_number": effective.get("version_number"),
                "policy_assignment_state": effective.get("assignment_state"),
                "dns_filter_state": st.dns_filter_state if st else "unknown",
                "dns_filter_error": st.dns_filter_error if st else None,
            }
        )


class DeviceLocationUploadAPIView(APIView):
    authentication_classes = [DeviceJWTAuthentication]
    permission_classes = [IsEnrolledDevice]

    def post(self, request):
        items = request.data.get("locations")
        try:
            result = ingest_locations(
                device=request.user.device,
                items=items if items is not None else request.data if isinstance(request.data, list) else [],
                request_meta=request_meta(request),
            )
        except DeviceAuthError as exc:
            return Response({"detail": str(exc), "code": exc.code}, status=status.HTTP_401_UNAUTHORIZED)
        except LocationError as exc:
            http_status = status.HTTP_400_BAD_REQUEST
            if exc.code == "invalid_batch":
                http_status = status.HTTP_400_BAD_REQUEST
            return Response({"detail": str(exc), "code": exc.code}, status=http_status)
        http_status = status.HTTP_200_OK
        if result["rejected"] and any(item["code"] == "rate_limited" for item in result["rejected"]) and not result["accepted"]:
            http_status = status.HTTP_429_TOO_MANY_REQUESTS
        return Response(result, status=http_status)


class DevicePolicyAPIView(APIView):
    authentication_classes = [DeviceJWTAuthentication]
    permission_classes = [IsEnrolledDevice]

    def get(self, request):
        from apps.policies.device_policy import get_device_effective_policy

        payload = get_device_effective_policy(device=request.user.device)
        etag = payload.get("etag")
        inm = request.headers.get("If-None-Match") or request.META.get("HTTP_IF_NONE_MATCH")
        if etag and inm and inm.strip() == etag:
            return Response(status=status.HTTP_304_NOT_MODIFIED)
        body = {k: v for k, v in payload.items() if k != "etag"}
        response = Response(body)
        if etag:
            response["ETag"] = etag
        return response


class DevicePolicyAckAPIView(APIView):
    authentication_classes = [DeviceJWTAuthentication]
    permission_classes = [IsEnrolledDevice]

    def post(self, request):
        from apps.policies.device_policy import acknowledge_device_policy
        from apps.policies.exceptions import PolicyError

        data = request.data
        try:
            result = acknowledge_device_policy(
                device=request.user.device,
                policy_version_id=data.get("policy_version_id"),
                version_number=data.get("version_number"),
                content_hash=data.get("content_hash"),
                applied_at=data.get("applied_at"),
                result=data.get("result") or "",
                client_event_id=data.get("client_event_id"),
                request_meta=request_meta(request),
            )
        except PolicyError as exc:
            return Response({"detail": str(exc), "code": exc.code}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result)


class DeviceFcmTokenAPIView(APIView):
    """Register or clear the device FCM registration token for policy wake."""

    authentication_classes = [DeviceJWTAuthentication]
    permission_classes = [IsEnrolledDevice]

    def post(self, request):
        from apps.devices.fcm import clear_fcm_token, register_fcm_token

        data = request.data
        token = data.get("token")
        device = request.user.device
        if token in (None, ""):
            clear_fcm_token(device=device)
            return Response({"ok": True, "registered": False})
        try:
            register_fcm_token(device=device, token=str(token))
        except ValueError:
            return Response(
                {"detail": "Invalid FCM token.", "code": "invalid_fcm_token"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({"ok": True, "registered": True})
