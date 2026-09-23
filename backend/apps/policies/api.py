from __future__ import annotations

from django.utils.dateparse import parse_datetime
from rest_framework import serializers, status
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.mixins import OrganizationAPIMixin
from apps.audit.services import request_meta
from apps.policies.assignments import (
    assign_policy_to_device,
    create_policy,
    resolve_effective_version,
    unassign_device_policy,
    update_device_policy_assignment,
    update_policy_metadata,
)
from apps.policies.exceptions import PolicyError
from apps.policies.lifecycle import (
    create_draft_version,
    publish_version,
    rollback_to_version,
    update_draft_version,
)
from apps.policies.models import (
    DevicePolicyAssignment,
    Policy,
    PolicySchedule,
    PolicyVersion,
    PolicyVersionStatus,
)
from apps.policies.schedules import cancel_policy_schedule, schedule_policy_publish


def _policy_error(exc: PolicyError):
    if exc.code in {
        "policy_not_found",
        "version_not_found",
        "device_not_found",
        "assignment_not_found",
        "schedule_not_found",
    }:
        raise NotFound(str(exc)) from exc

    class PolicyAPIError(APIException):
        status_code = (
            status.HTTP_409_CONFLICT
            if exc.code in {"assignment_exists", "schedule_exists"}
            else status.HTTP_400_BAD_REQUEST
        )
        default_code = exc.code

    raise PolicyAPIError(detail={"detail": str(exc), "code": exc.code}) from exc


def org_policy(organization, policy_id) -> Policy:
    policy = Policy.objects.filter(pk=policy_id, organization=organization).first()
    if policy is None:
        raise NotFound("Policy not found.")
    return policy


def org_version(organization, policy_id, version_id) -> PolicyVersion:
    version = (
        PolicyVersion.objects.filter(
            pk=version_id,
            policy_id=policy_id,
            organization=organization,
        )
        .select_related("policy")
        .first()
    )
    if version is None:
        raise NotFound("Policy version not found.")
    return version


def org_assignment(organization, assignment_id) -> DevicePolicyAssignment:
    assignment = (
        DevicePolicyAssignment.objects.filter(pk=assignment_id, organization=organization)
        .select_related("device", "policy", "pinned_version")
        .first()
    )
    if assignment is None:
        raise NotFound("Assignment not found.")
    return assignment


class PolicyVersionListSerializer(serializers.ModelSerializer):
    class Meta:
        model = PolicyVersion
        fields = (
            "id",
            "version_number",
            "status",
            "schema_version",
            "content_hash",
            "created_at",
            "published_at",
            "superseded_at",
            "created_by",
            "published_by",
        )
        read_only_fields = fields


class PolicyVersionDetailSerializer(PolicyVersionListSerializer):
    class Meta(PolicyVersionListSerializer.Meta):
        fields = PolicyVersionListSerializer.Meta.fields + ("document",)
        read_only_fields = fields


class PolicyListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Policy
        fields = (
            "id",
            "name",
            "description",
            "archived_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class PolicyDetailSerializer(serializers.ModelSerializer):
    current_published_version = serializers.SerializerMethodField()
    assignment_count = serializers.SerializerMethodField()
    initial_version = serializers.SerializerMethodField()

    class Meta:
        model = Policy
        fields = (
            "id",
            "name",
            "description",
            "archived_at",
            "created_at",
            "updated_at",
            "current_published_version",
            "assignment_count",
            "initial_version",
        )
        read_only_fields = fields

    def get_current_published_version(self, obj):
        version = (
            obj.versions.filter(status=PolicyVersionStatus.PUBLISHED)
            .order_by("-version_number")
            .first()
        )
        if version is None:
            return None
        return PolicyVersionListSerializer(version).data

    def get_assignment_count(self, obj):
        return obj.device_assignments.count()

    def get_initial_version(self, obj):
        version = self.context.get("initial_version")
        if version is None:
            return None
        return PolicyVersionListSerializer(version).data


class AssignmentSerializer(serializers.ModelSerializer):
    device_id = serializers.UUIDField(read_only=True)
    policy_id = serializers.UUIDField(read_only=True)
    pinned_version_id = serializers.UUIDField(read_only=True, allow_null=True)
    assigned_by_id = serializers.UUIDField(read_only=True, allow_null=True)
    effective_version = serializers.SerializerMethodField()

    class Meta:
        model = DevicePolicyAssignment
        fields = (
            "id",
            "device_id",
            "policy_id",
            "pinned_version_id",
            "assigned_by_id",
            "assigned_at",
            "updated_at",
            "effective_version",
        )
        read_only_fields = fields

    def get_effective_version(self, obj):
        version = resolve_effective_version(obj)
        if version is None:
            return None
        return PolicyVersionListSerializer(version).data


class PolicyListCreateAPIView(OrganizationAPIMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        policies = Policy.objects.filter(organization=self.organization).order_by("name")
        return Response(PolicyListSerializer(policies, many=True).data)

    def post(self, request):
        if not self.membership.can_manage:
            raise PermissionDenied("This action requires an owner or admin role.")
        try:
            policy, version = create_policy(
                organization=self.organization,
                name=request.data.get("name") or "",
                description=request.data.get("description") or "",
                actor_user=request.user,
                request_meta=request_meta(request),
            )
        except PolicyError as exc:
            _policy_error(exc)
        data = PolicyDetailSerializer(policy, context={"initial_version": version}).data
        return Response(data, status=status.HTTP_201_CREATED)


class PolicyDetailAPIView(OrganizationAPIMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, policy_id):
        policy = org_policy(self.organization, policy_id)
        return Response(PolicyDetailSerializer(policy).data)

    def patch(self, request, policy_id):
        if not self.membership.can_manage:
            raise PermissionDenied("This action requires an owner or admin role.")
        org_policy(self.organization, policy_id)
        kwargs = {}
        if "name" in request.data:
            kwargs["name"] = request.data.get("name")
        if "description" in request.data:
            kwargs["description"] = request.data.get("description")
        if "archived" in request.data:
            kwargs["archived"] = bool(request.data.get("archived"))
        try:
            policy = update_policy_metadata(
                organization=self.organization,
                policy_id=policy_id,
                actor_user=request.user,
                request_meta=request_meta(request),
                **kwargs,
            )
        except PolicyError as exc:
            _policy_error(exc)
        return Response(PolicyDetailSerializer(policy).data)


class PolicyVersionListCreateAPIView(OrganizationAPIMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, policy_id):
        org_policy(self.organization, policy_id)
        versions = PolicyVersion.objects.filter(
            policy_id=policy_id,
            organization=self.organization,
        ).order_by("-version_number")
        return Response(PolicyVersionListSerializer(versions, many=True).data)

    def post(self, request, policy_id):
        if not self.membership.can_manage:
            raise PermissionDenied("This action requires an owner or admin role.")
        org_policy(self.organization, policy_id)
        document = request.data.get("document") if "document" in request.data else None
        source = request.data.get("source_version_id")
        try:
            version = create_draft_version(
                organization=self.organization,
                policy_id=policy_id,
                actor_user=request.user,
                document=document,
                copy_from_version_id=source,
                request_meta=request_meta(request),
            )
        except PolicyError as exc:
            _policy_error(exc)
        return Response(PolicyVersionDetailSerializer(version).data, status=status.HTTP_201_CREATED)


class PolicyVersionDetailAPIView(OrganizationAPIMixin, APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, policy_id, version_id):
        if not self.membership.can_manage:
            raise PermissionDenied("This action requires an owner or admin role.")
        org_version(self.organization, policy_id, version_id)
        if "document" not in request.data:
            raise ValidationError({"document": "This field is required."})
        try:
            version = update_draft_version(
                organization=self.organization,
                version_id=version_id,
                document=request.data.get("document"),
                actor_user=request.user,
            )
        except PolicyError as exc:
            _policy_error(exc)
        # Ensure URL policy_id matches the version's policy (org_version already scoped).
        if str(version.policy_id) != str(policy_id):
            raise NotFound("Policy version not found.")
        return Response(PolicyVersionDetailSerializer(version).data)


class PolicyVersionPublishAPIView(OrganizationAPIMixin, APIView):
    permission_classes = [IsAuthenticated]
    manage_required = True

    def post(self, request, policy_id, version_id):
        org_version(self.organization, policy_id, version_id)
        try:
            version = publish_version(
                organization=self.organization,
                version_id=version_id,
                actor_user=request.user,
                request_meta=request_meta(request),
            )
        except PolicyError as exc:
            _policy_error(exc)
        if str(version.policy_id) != str(policy_id):
            raise NotFound("Policy version not found.")
        return Response(PolicyVersionDetailSerializer(version).data)


class PolicyVersionRollbackAPIView(OrganizationAPIMixin, APIView):
    permission_classes = [IsAuthenticated]
    manage_required = True

    def post(self, request, policy_id, version_id):
        target = org_version(self.organization, policy_id, version_id)
        try:
            version = rollback_to_version(
                organization=self.organization,
                target_version_id=target.id,
                actor_user=request.user,
                request_meta=request_meta(request),
            )
        except PolicyError as exc:
            _policy_error(exc)
        return Response(PolicyVersionDetailSerializer(version).data, status=status.HTTP_201_CREATED)


class AssignmentListCreateAPIView(OrganizationAPIMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        assignments = (
            DevicePolicyAssignment.objects.filter(organization=self.organization)
            .select_related("device", "policy", "pinned_version")
            .order_by("-assigned_at")
        )
        return Response(AssignmentSerializer(assignments, many=True).data)

    def post(self, request):
        if not self.membership.can_manage:
            raise PermissionDenied("This action requires an owner or admin role.")
        try:
            assignment = assign_policy_to_device(
                organization=self.organization,
                device_id=request.data.get("device_id"),
                policy_id=request.data.get("policy_id"),
                pinned_version_id=request.data.get("pinned_version_id"),
                actor_user=request.user,
                request_meta=request_meta(request),
            )
        except PolicyError as exc:
            _policy_error(exc)
        assignment = org_assignment(self.organization, assignment.id)
        return Response(AssignmentSerializer(assignment).data, status=status.HTTP_201_CREATED)


class AssignmentDetailAPIView(OrganizationAPIMixin, APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, assignment_id):
        if not self.membership.can_manage:
            raise PermissionDenied("This action requires an owner or admin role.")
        org_assignment(self.organization, assignment_id)
        kwargs = {}
        if "policy_id" in request.data:
            kwargs["policy_id"] = request.data.get("policy_id")
        if "pinned_version_id" in request.data:
            kwargs["pinned_version_id"] = request.data.get("pinned_version_id")
        try:
            assignment = update_device_policy_assignment(
                organization=self.organization,
                assignment_id=assignment_id,
                actor_user=request.user,
                request_meta=request_meta(request),
                **kwargs,
            )
        except PolicyError as exc:
            _policy_error(exc)
        assignment = org_assignment(self.organization, assignment.id)
        return Response(AssignmentSerializer(assignment).data)

    def delete(self, request, assignment_id):
        if not self.membership.can_manage:
            raise PermissionDenied("This action requires an owner or admin role.")
        org_assignment(self.organization, assignment_id)
        try:
            unassign_device_policy(
                organization=self.organization,
                assignment_id=assignment_id,
                actor_user=request.user,
                request_meta=request_meta(request),
            )
        except PolicyError as exc:
            _policy_error(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PolicyScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = PolicySchedule
        fields = (
            "id",
            "policy",
            "version",
            "activate_at",
            "status",
            "created_by",
            "created_at",
            "completed_at",
            "last_error",
        )
        read_only_fields = fields


def org_schedule(organization, schedule_id) -> PolicySchedule:
    schedule = (
        PolicySchedule.objects.filter(pk=schedule_id, organization=organization)
        .select_related("policy", "version")
        .first()
    )
    if schedule is None:
        raise NotFound("Schedule not found.")
    return schedule


class PolicyScheduleListCreateAPIView(OrganizationAPIMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        schedules = (
            PolicySchedule.objects.filter(organization=self.organization)
            .select_related("policy", "version")
            .order_by("activate_at")
        )
        return Response(PolicyScheduleSerializer(schedules, many=True).data)

    def post(self, request):
        if not self.membership.can_manage:
            raise PermissionDenied("This action requires an owner or admin role.")
        raw_activate = request.data.get("activate_at")
        activate_at = raw_activate
        if isinstance(raw_activate, str):
            activate_at = parse_datetime(raw_activate)
            if activate_at is None:
                raise ValidationError({"activate_at": "Invalid ISO-8601 datetime."})
        try:
            schedule = schedule_policy_publish(
                organization=self.organization,
                policy_id=request.data.get("policy_id"),
                version_id=request.data.get("version_id"),
                activate_at=activate_at,
                actor_user=request.user,
                request_meta=request_meta(request),
            )
        except PolicyError as exc:
            _policy_error(exc)
        schedule = org_schedule(self.organization, schedule.id)
        return Response(PolicyScheduleSerializer(schedule).data, status=status.HTTP_201_CREATED)


class PolicyScheduleDetailAPIView(OrganizationAPIMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, schedule_id):
        schedule = org_schedule(self.organization, schedule_id)
        return Response(PolicyScheduleSerializer(schedule).data)

    def delete(self, request, schedule_id):
        if not self.membership.can_manage:
            raise PermissionDenied("This action requires an owner or admin role.")
        org_schedule(self.organization, schedule_id)
        try:
            cancel_policy_schedule(
                organization=self.organization,
                schedule_id=schedule_id,
                actor_user=request.user,
                request_meta=request_meta(request),
            )
        except PolicyError as exc:
            _policy_error(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)
