from django.contrib import messages
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import FormView, TemplateView

from apps.accounts.mixins import OrganizationContextMixin
from apps.audit.models import AuditEvent
from apps.audit.services import request_meta
from apps.devices.forms import EnrollmentCreateForm, enrollment_qr_svg
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


class HomeView(OrganizationContextMixin, TemplateView):
    template_name = "dashboard/home.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        org = self.request.organization
        devices = Device.objects.filter(organization=org)
        ctx.update(
            {
                "device_count": devices.count(),
                "enrolled_count": devices.exclude(enrolled_at=None).filter(is_active=True).count(),
                "pending_enrollments": EnrollmentSession.objects.filter(
                    organization=org,
                    status=EnrollmentStatus.PENDING,
                    expires_at__gt=timezone.now(),
                ).count(),
                "recent_audit": AuditEvent.objects.filter(organization=org)[:8],
            }
        )
        return ctx


class DeviceListView(OrganizationContextMixin, TemplateView):
    template_name = "dashboard/devices.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["devices"] = Device.objects.filter(organization=self.request.organization).select_related("status")
        return ctx


class DeviceDetailView(OrganizationContextMixin, TemplateView):
    template_name = "dashboard/device_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        device = get_object_or_404(
            Device.objects.select_related("status", "status__last_location"),
            pk=kwargs["device_id"],
            organization=self.request.organization,
        )
        ctx["device"] = device
        ctx["can_view_location"] = self.request.membership.can_manage
        if ctx["can_view_location"]:
            latest = latest_location(device)
            ctx["latest_location"] = serialize_location(latest)
            ctx["location_history"] = [serialize_location(record) for record in location_history(device, limit=50)]
            if latest is None:
                if not device.location_collection_enabled:
                    ctx["location_empty_reason"] = "Location collection is not enabled."
                elif not device.status.last_seen_at:
                    ctx["location_empty_reason"] = "Device has not checked in yet (offline / no heartbeat)."
                else:
                    ctx["location_empty_reason"] = "No location fix has been received yet."
            else:
                ctx["location_empty_reason"] = None
        return ctx


class DeviceRenameView(OrganizationContextMixin, TemplateView):
    manage_required = True
    http_method_names = ["post"]

    def post(self, request, device_id):
        device = get_object_or_404(Device, pk=device_id, organization=request.organization)
        name = (request.POST.get("display_name") or "").strip()
        if not name:
            messages.error(request, "Display name is required.")
            return HttpResponseRedirect(reverse("dashboard:device_detail", args=[device.id]))
        try:
            rename_device(
                device=device,
                display_name=name,
                actor_user=request.user,
                request_meta=request_meta(request),
            )
            messages.success(request, "Device name updated.")
        except EnrollmentError as exc:
            messages.error(request, str(exc))
        return HttpResponseRedirect(reverse("dashboard:device_detail", args=[device.id]))


class DeviceRevokeView(OrganizationContextMixin, TemplateView):
    manage_required = True
    http_method_names = ["post"]

    def post(self, request, device_id):
        device = get_object_or_404(Device, pk=device_id, organization=request.organization)
        try:
            revoke_device(device=device, actor_user=request.user, request_meta=request_meta(request))
            messages.success(request, "Device credentials revoked. The device can no longer be managed.")
        except EnrollmentError as exc:
            messages.error(request, str(exc))
        return HttpResponseRedirect(reverse("dashboard:device_detail", args=[device.id]))


class DeviceLocationEnableView(OrganizationContextMixin, TemplateView):
    manage_required = True
    http_method_names = ["post"]

    def post(self, request, device_id):
        device = get_object_or_404(Device, pk=device_id, organization=request.organization)
        try:
            set_location_collection(
                device=device,
                enabled=True,
                actor_user=request.user,
                request_meta=request_meta(request),
            )
            messages.success(
                request,
                "Location collection enabled. The device must still accept on-device disclosure and grant OS location permission.",
            )
        except EnrollmentError as exc:
            messages.error(request, str(exc))
        return HttpResponseRedirect(reverse("dashboard:device_detail", args=[device.id]))


class DeviceLocationDisableView(OrganizationContextMixin, TemplateView):
    manage_required = True
    http_method_names = ["post"]

    def post(self, request, device_id):
        device = get_object_or_404(Device, pk=device_id, organization=request.organization)
        set_location_collection(
            device=device,
            enabled=False,
            actor_user=request.user,
            request_meta=request_meta(request),
        )
        messages.success(request, "Location collection disabled. The device will stop uploading new points.")
        return HttpResponseRedirect(reverse("dashboard:device_detail", args=[device.id]))


class EnrollDeviceView(OrganizationContextMixin, FormView):
    manage_required = True
    template_name = "dashboard/enroll.html"
    form_class = EnrollmentCreateForm
    success_url = reverse_lazy("dashboard:enroll")

    def form_valid(self, form):
        created = create_enrollment_session(
            organization=self.request.organization,
            created_by=self.request.user,
            allowed_provisioning_modes=form.cleaned_data["allowed_provisioning_modes"],
            request_meta=request_meta(self.request),
        )
        qr_svg = enrollment_qr_svg(created.payload)
        return self.render_to_response(
            self.get_context_data(
                form=EnrollmentCreateForm(),
                created_session=created.session,
                raw_secret=created.raw_secret,
                payload=created.payload,
                qr_svg=qr_svg,
            )
        )


class CancelEnrollmentView(OrganizationContextMixin, TemplateView):
    manage_required = True
    http_method_names = ["post"]

    def post(self, request, session_id):
        session = get_object_or_404(
            EnrollmentSession,
            pk=session_id,
            organization=request.organization,
        )
        try:
            cancel_enrollment_session(
                session=session,
                actor_user=request.user,
                request_meta=request_meta(request),
            )
            messages.success(request, "Enrollment session cancelled.")
        except EnrollmentError as exc:
            messages.error(request, str(exc))
        return HttpResponseRedirect(reverse("dashboard:enroll"))


class AuditListView(OrganizationContextMixin, TemplateView):
    template_name = "dashboard/audit.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        org = self.request.organization
        qs = AuditEvent.objects.filter(organization=org).select_related("actor_user", "target_device")
        action = self.request.GET.get("action") or ""
        actor = self.request.GET.get("actor") or ""
        device = self.request.GET.get("device") or ""
        date_from = self.request.GET.get("from") or ""
        date_to = self.request.GET.get("to") or ""
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
        ctx.update(
            {
                "events": qs[:200],
                "filter_action": action,
                "filter_actor": actor,
                "filter_device": device,
                "filter_from": date_from,
                "filter_to": date_to,
                "devices": Device.objects.filter(organization=org),
            }
        )
        return ctx


class PolicyListView(OrganizationContextMixin, TemplateView):
    template_name = "dashboard/policies.html"

    def get_context_data(self, **kwargs):
        from apps.policies.models import Policy

        ctx = super().get_context_data(**kwargs)
        ctx["policies"] = Policy.objects.filter(organization=self.request.organization).order_by("name")
        ctx["can_manage"] = self.request.membership.can_manage
        return ctx


class PolicyCreateView(OrganizationContextMixin, TemplateView):
    manage_required = True
    http_method_names = ["post"]

    def post(self, request):
        from apps.policies.assignments import create_policy
        from apps.policies.exceptions import PolicyError

        try:
            policy, _version = create_policy(
                organization=request.organization,
                name=request.POST.get("name") or "",
                description=request.POST.get("description") or "",
                actor_user=request.user,
                request_meta=request_meta(request),
            )
            messages.success(request, f"Policy “{policy.name}” created with an empty draft.")
            return HttpResponseRedirect(reverse("dashboard:policy_detail", args=[policy.id]))
        except PolicyError as exc:
            messages.error(request, str(exc))
            return HttpResponseRedirect(reverse("dashboard:policies"))


class PolicyDetailView(OrganizationContextMixin, TemplateView):
    template_name = "dashboard/policy_detail.html"

    def get_context_data(self, **kwargs):
        from apps.policies.models import Policy, PolicyVersion, PolicyVersionStatus

        ctx = super().get_context_data(**kwargs)
        policy = get_object_or_404(
            Policy,
            pk=kwargs["policy_id"],
            organization=self.request.organization,
        )
        ctx["policy"] = policy
        ctx["versions"] = policy.versions.order_by("-version_number")
        ctx["published"] = policy.versions.filter(status=PolicyVersionStatus.PUBLISHED).first()
        ctx["can_manage"] = self.request.membership.can_manage
        ctx["devices"] = Device.objects.filter(organization=self.request.organization).order_by("display_name")
        ctx["assignments"] = policy.device_assignments.select_related("device", "pinned_version")
        return ctx


class PolicyPublishView(OrganizationContextMixin, TemplateView):
    manage_required = True
    http_method_names = ["post"]

    def post(self, request, policy_id, version_id):
        from apps.policies.exceptions import PolicyError
        from apps.policies.lifecycle import publish_version
        from apps.policies.models import PolicyVersion

        version = get_object_or_404(
            PolicyVersion,
            pk=version_id,
            policy_id=policy_id,
            organization=request.organization,
        )
        try:
            publish_version(
                organization=request.organization,
                version_id=version.id,
                actor_user=request.user,
                request_meta=request_meta(request),
            )
            messages.success(request, f"Published version {version.version_number}.")
        except PolicyError as exc:
            messages.error(request, str(exc))
        return HttpResponseRedirect(reverse("dashboard:policy_detail", args=[policy_id]))


class PolicyAssignView(OrganizationContextMixin, TemplateView):
    manage_required = True
    http_method_names = ["post"]

    def post(self, request, policy_id):
        from apps.policies.assignments import assign_policy_to_device
        from apps.policies.exceptions import PolicyError

        try:
            assign_policy_to_device(
                organization=request.organization,
                device_id=request.POST.get("device_id"),
                policy_id=policy_id,
                actor_user=request.user,
                request_meta=request_meta(request),
            )
            messages.success(request, "Policy assigned to device.")
        except PolicyError as exc:
            messages.error(request, str(exc))
        return HttpResponseRedirect(reverse("dashboard:policy_detail", args=[policy_id]))
