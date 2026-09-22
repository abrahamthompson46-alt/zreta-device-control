from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.mixins import OrganizationAPIMixin

from .models import AuditEvent


class AuditEventSerializer(serializers.ModelSerializer):
    actor_email = serializers.SerializerMethodField()
    target_device_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = AuditEvent
        fields = (
            "id",
            "action",
            "result",
            "timestamp",
            "actor_email",
            "target_device_id",
            "old_snapshot",
            "new_snapshot",
        )

    def get_actor_email(self, obj):
        return obj.actor_user.email if obj.actor_user_id else None


class AuditEventListAPIView(OrganizationAPIMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = AuditEvent.objects.filter(organization=self.organization).select_related(
            "actor_user", "target_device"
        )
        action = request.query_params.get("action")
        actor = request.query_params.get("actor")
        device = request.query_params.get("device")
        date_from = request.query_params.get("from")
        date_to = request.query_params.get("to")
        if action:
            qs = qs.filter(action=action)
        if actor:
            qs = qs.filter(actor_user__email__icontains=actor)
        if device:
            qs = qs.filter(target_device_id=device)
        if date_from:
            qs = qs.filter(timestamp__date__gte=date_from)
        if date_to:
            qs = qs.filter(timestamp__date__lte=date_to)
        data = AuditEventSerializer(qs[:200], many=True).data
        return Response(data)
