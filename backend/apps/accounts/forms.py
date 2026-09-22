from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, PasswordResetForm, SetPasswordForm, UserCreationForm
from django import forms

from .models import Organization


class EmailAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(label="Email", widget=forms.EmailInput(attrs={"autofocus": True, "class": "form-control"}))
    password = forms.CharField(label="Password", strip=False, widget=forms.PasswordInput(attrs={"class": "form-control"}))


class RegistrationForm(UserCreationForm):
    email = forms.EmailField(widget=forms.EmailInput(attrs={"class": "form-control", "autofocus": True}))
    organization_name = forms.CharField(
        max_length=150,
        required=False,
        label="Family / organization name",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Optional"}),
    )
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput(attrs={"class": "form-control"}))
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput(attrs={"class": "form-control"}))

    class Meta:
        model = get_user_model()
        fields = ("email",)

    def save(self, commit=True):
        # Persistence is handled by register_family_account.
        return super().save(commit=False)


class StyledPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class StyledPasswordResetForm(PasswordResetForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].widget.attrs.setdefault("class", "form-control")


class StyledSetPasswordForm(SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class OrganizationSwitchForm(forms.Form):
    organization = forms.ModelChoiceField(queryset=Organization.objects.none())

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["organization"].queryset = Organization.objects.filter(
                memberships__user=user,
                is_active=True,
            )
        self.fields["organization"].widget.attrs.setdefault("class", "form-select")
