from __future__ import annotations

import base64
import html
import json

import pytest
from django.urls import reverse

from apps.devices.forms import enrollment_qr_data_uri
from apps.devices.services import (
    build_enrollment_payload,
    canonical_enrollment_payload_json,
    create_enrollment_session,
)

pytestmark = pytest.mark.django_db


def test_canonical_enrollment_json_is_compact_and_ordered(owner_bundle):
    created = create_enrollment_session(
        organization=owner_bundle["org"],
        created_by=owner_bundle["user"],
    )
    text = canonical_enrollment_payload_json(created.payload)
    assert text == json.dumps(
        {
            "v": 1,
            "api_base": created.payload["api_base"],
            "enrollment_session_id": str(created.session.id),
            "enrollment_secret": created.raw_secret,
        },
        separators=(",", ":"),
        ensure_ascii=True,
    )
    # No spaces — identical form used for QR content and paste box.
    assert " " not in text
    parsed = json.loads(text)
    assert list(parsed.keys()) == [
        "v",
        "api_base",
        "enrollment_session_id",
        "enrollment_secret",
    ]


def test_enrollment_qr_png_encodes_canonical_json(owner_bundle):
    created = create_enrollment_session(
        organization=owner_bundle["org"],
        created_by=owner_bundle["user"],
    )
    expected = canonical_enrollment_payload_json(created.payload)
    uri = enrollment_qr_data_uri(created.payload)
    assert uri.startswith("data:image/png;base64,")
    raw = base64.b64decode(uri.split(",", 1)[1])
    assert raw.startswith(b"\x89PNG\r\n\x1a\n")
    # Re-encode must be deterministic for the same payload.
    assert enrollment_qr_data_uri(created.payload) == uri
    # QR content source is the same string the dashboard paste box shows.
    assert expected == canonical_enrollment_payload_json(
        build_enrollment_payload(created.session, created.raw_secret)
    )


def test_dashboard_enroll_shows_png_and_matching_json(client, owner_bundle, password):
    client.post("/login/", {"username": owner_bundle["user"].email, "password": password})
    response = client.post(
        reverse("dashboard:enroll"),
        {"allowed_provisioning_modes": ["device_owner"]},
    )
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "Waiting for device enrollment" in body
    assert 'src="data:image/png;base64,' in body
    assert 'id="enrollment-payload-json"' in body
    # Extract textarea contents and confirm it is valid enrollment JSON.
    start = body.index('id="enrollment-payload-json"')
    open_tag_end = body.index(">", start) + 1
    close = body.index("</textarea>", open_tag_end)
    payload_json = html.unescape(body[open_tag_end:close]).strip()
    parsed = json.loads(payload_json)
    assert parsed["v"] == 1
    assert "enrollment_secret" in parsed
    assert "api_base" in parsed
    # Secret appears once in the paste JSON; still shown in secret box (by design, once).
    assert payload_json.count(parsed["enrollment_secret"]) == 1
