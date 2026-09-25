import base64
from io import BytesIO

import segno
from django import forms

from .models import ProvisioningMode
from .services import canonical_enrollment_payload_json


class EnrollmentCreateForm(forms.Form):
    allowed_provisioning_modes = forms.MultipleChoiceField(
        choices=ProvisioningMode.choices,
        initial=[ProvisioningMode.DEVICE_OWNER],
        widget=forms.CheckboxSelectMultiple,
        required=True,
    )


def enrollment_qr_data_uri(payload: dict) -> str:
    """
    PNG data-URI QR encoding the canonical enrollment JSON.

    Prefer PNG over stroke-based SVG: CSS-scaled SVG paths anti-alias poorly and
    were unreliable for phone-camera scans of the dashboard QR on physical devices.
    """
    content = canonical_enrollment_payload_json(payload)
    qr = segno.make(content, error="m")
    buffer = BytesIO()
    # scale=8 + border=4 → crisp modules; light fill gives explicit quiet zone contrast.
    qr.save(buffer, kind="png", scale=8, border=4, dark="#000000", light="#ffffff")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def enrollment_qr_svg(payload: dict) -> str:
    """Deprecated SVG path kept for callers; prefer enrollment_qr_data_uri."""
    content = canonical_enrollment_payload_json(payload)
    qr = segno.make(content, error="m")
    buffer = BytesIO()
    qr.save(buffer, kind="svg", xmldecl=False, svgns=False, scale=4)
    return buffer.getvalue().decode("utf-8")
