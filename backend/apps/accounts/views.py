from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import (
    LoginView,
    LogoutView,
    PasswordChangeView,
    PasswordResetCompleteView,
    PasswordResetConfirmView,
    PasswordResetDoneView,
    PasswordResetView,
)
from django.http import HttpResponseRedirect
from django.urls import reverse_lazy
from django.views.generic import FormView

from apps.audit.services import record_audit, request_meta

from .authorization import SESSION_ORG_KEY, require_membership
from .forms import (
    EmailAuthenticationForm,
    OrganizationSwitchForm,
    RegistrationForm,
    StyledPasswordChangeForm,
    StyledPasswordResetForm,
    StyledSetPasswordForm,
)
from .services import register_family_account


class RegisterView(FormView):
    template_name = "accounts/register.html"
    form_class = RegistrationForm
    success_url = reverse_lazy("dashboard:home")

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return HttpResponseRedirect(self.get_success_url())
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        user, organization, _membership = register_family_account(
            email=form.cleaned_data["email"],
            password=form.cleaned_data["password1"],
            organization_name=form.cleaned_data.get("organization_name") or "",
        )
        login(self.request, user)
        self.request.session[SESSION_ORG_KEY] = str(organization.id)
        messages.success(self.request, "Account created. This organization is a family tenant.")
        return super().form_valid(form)


class EmailLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        membership = self.request.user.memberships.select_related("organization").first()
        meta = request_meta(self.request)
        if membership:
            self.request.session[SESSION_ORG_KEY] = str(membership.organization_id)
            record_audit(
                organization=membership.organization,
                actor_user=self.request.user,
                action="user.login",
                result="success",
                **meta,
            )
        return response

    def form_invalid(self, form):
        email = (form.data.get("username") or "").strip()
        membership = None
        if email:
            from .models import Membership

            membership = (
                Membership.objects.select_related("organization", "user")
                .filter(user__email__iexact=email)
                .first()
            )
        if membership:
            record_audit(
                organization=membership.organization,
                actor_user=membership.user,
                action="user.login",
                result="failure",
                **request_meta(self.request),
            )
        return super().form_invalid(form)


class EmailLogoutView(LogoutView):
    next_page = reverse_lazy("accounts:login")


class ChangePasswordView(PasswordChangeView):
    form_class = StyledPasswordChangeForm
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("dashboard:home")

    def form_valid(self, form):
        messages.success(self.request, "Password updated.")
        if getattr(self.request, "organization", None):
            record_audit(
                organization=self.request.organization,
                actor_user=self.request.user,
                action="user.password_changed",
                result="success",
                **request_meta(self.request),
            )
        return super().form_valid(form)


class ResetPasswordView(PasswordResetView):
    form_class = StyledPasswordResetForm
    template_name = "accounts/password_reset.html"
    email_template_name = "accounts/password_reset_email.txt"
    success_url = reverse_lazy("accounts:password_reset_done")


class ResetPasswordDoneView(PasswordResetDoneView):
    template_name = "accounts/password_reset_done.html"


class ResetPasswordConfirmView(PasswordResetConfirmView):
    form_class = StyledSetPasswordForm
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")


class ResetPasswordCompleteView(PasswordResetCompleteView):
    template_name = "accounts/password_reset_complete.html"


class SwitchOrganizationView(LoginRequiredMixin, FormView):
    form_class = OrganizationSwitchForm
    template_name = "accounts/switch_organization.html"
    success_url = reverse_lazy("dashboard:home")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        organization = form.cleaned_data["organization"]
        require_membership(self.request.user, organization.id)
        self.request.session[SESSION_ORG_KEY] = str(organization.id)
        return super().form_valid(form)
