from __future__ import annotations

import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.serialization.pkcs7 import PKCS7Options, PKCS7SignatureBuilder
import datetime
from django.test import override_settings

from apps.devices.provisioning import (
    DPC_COMPONENT,
    build_device_owner_setup_document,
    build_device_owner_setup_qr,
    canonical_setup_json,
    urlsafe_sha256_checksum,
)


def test_setup_document_carries_enrollment_secret_not_parent_credentials():
    document = build_device_owner_setup_document(
        enrollment_payload={
            "v": 1,
            "api_base": "https://control.zreta.com",
            "enrollment_session_id": "11111111-1111-1111-1111-111111111111",
            "enrollment_secret": "one-time-secret",
        },
        download_url="https://control.zreta.com/dpc.apk",
        signature_checksum="abc=",
        package_checksum="def=",
    )
    assert document["android.app.extra.PROVISIONING_DEVICE_ADMIN_COMPONENT_NAME"] == DPC_COMPONENT
    extras = document["android.app.extra.PROVISIONING_ADMIN_EXTRAS_BUNDLE"]
    assert extras["enrollment_secret"] == "one-time-secret"
    assert extras["api_base"] == "https://control.zreta.com"
    text = canonical_setup_json(document)
    assert "password" not in text
    assert json.loads(text)["android.app.extra.PROVISIONING_LEAVE_ALL_SYSTEM_APPS_ENABLED"] is True


def test_checksum_is_urlsafe_sha256():
    value = urlsafe_sha256_checksum(b"zreta")
    assert "+" not in value and "/" not in value
    assert value.endswith("=")
    assert len(value) > 40


def _signed_apk(path: Path) -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "zreta-test")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=1))
        .sign(key, SHA256())
    )
    pkcs7 = (
        PKCS7SignatureBuilder()
        .set_data(b"apk")
        .add_signer(cert, key, SHA256())
        .sign(Encoding.DER, [PKCS7Options.Binary, PKCS7Options.DetachedSignature])
    )
    import zipfile

    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("AndroidManifest.xml", b"<manifest/>")
        archive.writestr("META-INF/CERT.RSA", pkcs7)


def test_setup_qr_uses_apk_checksums(tmp_path, settings):
    apk = tmp_path / "dpc.apk"
    _signed_apk(apk)
    settings.DPC_APK_PATH = str(apk)
    settings.PUBLIC_API_BASE_URL = "https://control.zreta.com"
    built = build_device_owner_setup_qr(
        {
            "api_base": "https://control.zreta.com",
            "enrollment_session_id": "11111111-1111-1111-1111-111111111111",
            "enrollment_secret": "secret-value",
        }
    )
    assert built is not None
    assert built.download_url == "https://control.zreta.com/dpc.apk"
    assert built.qr_data_uri.startswith("data:image/png;base64,")
    assert "secret-value" in built.payload_json


@override_settings(DPC_APK_PATH="")
def test_dpc_download_missing_is_404(client):
    response = client.get("/dpc.apk")
    assert response.status_code == 404


@pytest.mark.django_db
def test_dpc_download_serves_configured_file(client, settings, tmp_path):
    apk = tmp_path / "dpc.apk"
    apk.write_bytes(b"PK\x03\x04not-a-real-apk")
    settings.DPC_APK_PATH = str(apk)
    response = client.get("/dpc.apk")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/vnd.android.package-archive")
    body = b"".join(response.streaming_content)
    assert body.startswith(b"PK")
    assert b"enrollment_secret" not in body
