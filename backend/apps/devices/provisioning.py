"""Device Owner setup QR for the Android setup wizard. Not the in-app enrollment QR."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

from apps.devices.forms import qr_png_data_uri

DPC_COMPONENT = "com.zreta.devicecontrol/com.zreta.devicecontrol.dpc.ZretaDeviceAdminReceiver"
DOWNLOAD_PATH = "/dpc.apk"


def urlsafe_sha256_checksum(data: bytes) -> str:
    """URL-safe Base64 of SHA-256, with padding. Matches Android provisioning checksums."""
    digest = hashlib.sha256(data).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii")


def apk_signing_certificate_der(apk_path: Path) -> bytes:
    """DER certificate from the APK signature (v1 block, or the v2 signing block)."""
    data = apk_path.read_bytes()
    try:
        return _certificate_from_v1_block(data)
    except ValueError:
        return _certificate_from_v2_block(data)


def _certificate_from_v1_block(data: bytes) -> bytes:
    from cryptography.hazmat.primitives.serialization import Encoding
    from cryptography.hazmat.primitives.serialization.pkcs7 import load_der_pkcs7_certificates

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        rsa_names = [
            name
            for name in archive.namelist()
            if name.startswith("META-INF/") and name.upper().endswith((".RSA", ".EC"))
        ]
        if not rsa_names:
            raise ValueError("apk_has_no_v1_signature")
        pkcs7_der = archive.read(sorted(rsa_names)[0])
    certificates = load_der_pkcs7_certificates(pkcs7_der)
    if not certificates:
        raise ValueError("apk_certificate_missing")
    return certificates[0].public_bytes(Encoding.DER)


def _certificate_from_v2_block(data: bytes) -> bytes:
    """Read the first signer certificate from the APK Signature Scheme v2 block."""
    eocd = data.rfind(b"PK\x05\x06")
    if eocd < 0 or eocd + 22 > len(data):
        raise ValueError("apk_zip_directory_missing")
    central_offset = int.from_bytes(data[eocd + 16 : eocd + 20], "little")
    magic_at = central_offset - 16
    if data[magic_at:central_offset] != b"APK Sig Block 42":
        raise ValueError("apk_signing_block_missing")
    block_size = int.from_bytes(data[magic_at - 8 : magic_at], "little")
    pairs = data[central_offset - block_size : magic_at - 8]
    offset = 0
    v2_id = 0x7109871A
    v2_value = None
    while offset + 12 <= len(pairs):
        pair_len = int.from_bytes(pairs[offset : offset + 8], "little")
        pair_id = int.from_bytes(pairs[offset + 8 : offset + 12], "little")
        value = pairs[offset + 12 : offset + 8 + pair_len]
        if pair_id == v2_id:
            v2_value = value
            break
        offset += 8 + pair_len
    if not v2_value or len(v2_value) < 12:
        raise ValueError("apk_v2_signature_missing")
    # signers sequence, then the first signer, then signed data: digests, certificates.
    index = 4  # skip signers-sequence length
    signer_len = int.from_bytes(v2_value[index : index + 4], "little")
    index += 4
    signer = v2_value[index : index + signer_len]
    signed_len = int.from_bytes(signer[0:4], "little")
    signed = signer[4 : 4 + signed_len]
    cursor = 0
    digests_len = int.from_bytes(signed[cursor : cursor + 4], "little")
    cursor += 4 + digests_len
    cursor += 4  # certificates sequence length
    cert_len = int.from_bytes(signed[cursor : cursor + 4], "little")
    cursor += 4
    certificate = signed[cursor : cursor + cert_len]
    if not certificate or certificate[0] != 0x30:
        raise ValueError("apk_v2_certificate_missing")
    return certificate


def dpc_apk_path() -> Path | None:
    raw = getattr(settings, "DPC_APK_PATH", "") or ""
    if not str(raw).strip():
        return None
    path = Path(str(raw).strip())
    if not path.is_file():
        return None
    return path


def dpc_download_url() -> str:
    base = settings.PUBLIC_API_BASE_URL.rstrip("/")
    return base + DOWNLOAD_PATH


def build_device_owner_setup_document(
    *,
    enrollment_payload: dict,
    download_url: str,
    signature_checksum: str,
    package_checksum: str,
) -> dict:
    return {
        "android.app.extra.PROVISIONING_DEVICE_ADMIN_COMPONENT_NAME": DPC_COMPONENT,
        "android.app.extra.PROVISIONING_DEVICE_ADMIN_PACKAGE_DOWNLOAD_LOCATION": download_url,
        "android.app.extra.PROVISIONING_DEVICE_ADMIN_SIGNATURE_CHECKSUM": signature_checksum,
        "android.app.extra.PROVISIONING_DEVICE_ADMIN_PACKAGE_CHECKSUM": package_checksum,
        "android.app.extra.PROVISIONING_LEAVE_ALL_SYSTEM_APPS_ENABLED": True,
        "android.app.extra.PROVISIONING_ADMIN_EXTRAS_BUNDLE": {
            "api_base": str(enrollment_payload["api_base"]),
            "enrollment_session_id": str(enrollment_payload["enrollment_session_id"]),
            "enrollment_secret": str(enrollment_payload["enrollment_secret"]),
        },
    }


def canonical_setup_json(document: dict) -> str:
    return json.dumps(document, separators=(",", ":"), ensure_ascii=True)


@dataclass
class DeviceOwnerSetupQr:
    document: dict
    payload_json: str
    qr_data_uri: str
    download_url: str


def build_device_owner_setup_qr(enrollment_payload: dict) -> DeviceOwnerSetupQr | None:
    apk = dpc_apk_path()
    if apk is None:
        return None
    try:
        signature = urlsafe_sha256_checksum(apk_signing_certificate_der(apk))
        package = urlsafe_sha256_checksum(apk.read_bytes())
    except (OSError, ValueError, zipfile.BadZipFile):
        return None
    download_url = dpc_download_url()
    document = build_device_owner_setup_document(
        enrollment_payload=enrollment_payload,
        download_url=download_url,
        signature_checksum=signature,
        package_checksum=package,
    )
    text = canonical_setup_json(document)
    return DeviceOwnerSetupQr(
        document=document,
        payload_json=text,
        qr_data_uri=qr_png_data_uri(text),
        download_url=download_url,
    )
