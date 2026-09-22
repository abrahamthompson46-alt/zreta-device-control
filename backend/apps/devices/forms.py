import json
from io import BytesIO

import segno
from django import forms

from .models import ProvisioningMode


class EnrollmentCreateForm(forms.Form):
    allowed_provisioning_modes = forms.MultipleChoiceField(
        choices=ProvisioningMode.choices,
        initial=[ProvisioningMode.DEVICE_OWNER],
        widget=forms.CheckboxSelectMultiple,
        required=True,
    )


def enrollment_qr_svg(payload: dict) -> str:
    qr = segno.make(json.dumps(payload, separators=(",", ":")), error="m")
    buffer = BytesIO()
    qr.save(buffer, kind="svg", xmldecl=False, svgns=False, scale=4)
    return buffer.getvalue().decode("utf-8")
