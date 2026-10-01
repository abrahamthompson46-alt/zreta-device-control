"""Build schema-v1 policy documents from the dashboard editor.

Only keys already accepted by apps.policies.schema and enforced on Android are emitted.
Unchecked booleans are omitted so the next publish clears that restriction.
"""

from __future__ import annotations

from apps.policies.exceptions import PolicyError
from apps.policies.schema import (
    TRAFFIC_ENGINE_LOCAL_DNS_BLOCKLIST,
    empty_policy_document,
    validate_policy_document,
)


def _lines(value: str | None) -> list[str]:
    if not value:
        return []
    lines = []
    for raw in str(value).replace(",", "\n").splitlines():
        text = raw.strip()
        if text:
            lines.append(text)
    return lines


def _checked(post, name: str) -> bool:
    return str(post.get(name) or "").lower() in {"1", "true", "on", "yes"}


def document_from_editor_post(post) -> dict:
    """Return a validated schema-v1 document. Raises PolicyError on invalid input."""
    document = empty_policy_document()

    applications = {}
    for field in ("suspend_packages", "hide_packages", "uninstall_blocked_packages"):
        packages = _lines(post.get(field))
        if packages:
            applications[field] = packages
    document["applications"] = applications

    device = {}
    if _checked(post, "camera_disabled"):
        device["camera_disabled"] = True
    if _checked(post, "screen_capture_disabled"):
        device["screen_capture_disabled"] = True
    document["device"] = device

    calls = {}
    if _checked(post, "block_outgoing_calls"):
        calls["block_outgoing_calls"] = True
    if _checked(post, "block_sms"):
        calls["block_sms"] = True
    document["calls"] = calls

    internet = {}
    for field in (
        "disallow_config_wifi",
        "disallow_config_mobile_networks",
        "disallow_config_tethering",
        "disallow_config_vpn",
    ):
        if _checked(post, field):
            internet[field] = True
    domains = _lines(post.get("blocked_domains"))
    if domains:
        internet["traffic"] = {
            "enabled": True,
            "engine": TRAFFIC_ENGINE_LOCAL_DNS_BLOCKLIST,
            "blocked_domains": domains,
        }
    document["internet"] = internet

    screen = {}
    start = (post.get("bedtime_start") or "").strip()
    end = (post.get("bedtime_end") or "").strip()
    if start or end or _checked(post, "bedtime_block_outgoing_calls") or _lines(post.get("bedtime_suspend_packages")):
        if not start or not end:
            raise PolicyError(
                "A bedtime window needs both a start and an end time.",
                "invalid_section_field",
            )
        screen["bedtime_start"] = start
        screen["bedtime_end"] = end
        if _checked(post, "bedtime_block_outgoing_calls"):
            screen["bedtime_block_outgoing_calls"] = True
        bedtime_packages = _lines(post.get("bedtime_suspend_packages"))
        if bedtime_packages:
            screen["bedtime_suspend_packages"] = bedtime_packages
    document["screen_time"] = screen

    location = {}
    if _checked(post, "collection_desired"):
        location["collection_desired"] = True
    document["location"] = location

    return validate_policy_document(document)


def editor_initial(document: dict | None) -> dict:
    doc = document or empty_policy_document()
    apps = doc.get("applications") or {}
    device = doc.get("device") or {}
    calls = doc.get("calls") or {}
    internet = doc.get("internet") or {}
    traffic = internet.get("traffic") or {}
    screen = doc.get("screen_time") or {}
    location = doc.get("location") or {}

    def joined(values) -> str:
        if not isinstance(values, list):
            return ""
        return "\n".join(str(item) for item in values)

    return {
        "suspend_packages": joined(apps.get("suspend_packages")),
        "hide_packages": joined(apps.get("hide_packages")),
        "uninstall_blocked_packages": joined(apps.get("uninstall_blocked_packages")),
        "camera_disabled": device.get("camera_disabled") is True,
        "screen_capture_disabled": device.get("screen_capture_disabled") is True,
        "block_outgoing_calls": calls.get("block_outgoing_calls") is True,
        "block_sms": calls.get("block_sms") is True,
        "disallow_config_wifi": internet.get("disallow_config_wifi") is True,
        "disallow_config_mobile_networks": internet.get("disallow_config_mobile_networks") is True,
        "disallow_config_tethering": internet.get("disallow_config_tethering") is True,
        "disallow_config_vpn": internet.get("disallow_config_vpn") is True,
        "blocked_domains": joined(traffic.get("blocked_domains")),
        "bedtime_start": screen.get("bedtime_start") or "",
        "bedtime_end": screen.get("bedtime_end") or "",
        "bedtime_block_outgoing_calls": screen.get("bedtime_block_outgoing_calls") is True,
        "bedtime_suspend_packages": joined(screen.get("bedtime_suspend_packages")),
        "collection_desired": location.get("collection_desired") is True,
    }


def policy_summary(document: dict | None) -> list[str]:
    initial = editor_initial(document)
    lines = []
    if initial["suspend_packages"]:
        lines.append("Suspend apps: " + ", ".join(initial["suspend_packages"].splitlines()))
    if initial["hide_packages"]:
        lines.append("Hide apps: " + ", ".join(initial["hide_packages"].splitlines()))
    if initial["uninstall_blocked_packages"]:
        lines.append("Block uninstall: " + ", ".join(initial["uninstall_blocked_packages"].splitlines()))
    if initial["camera_disabled"]:
        lines.append("Camera disabled")
    if initial["screen_capture_disabled"]:
        lines.append("Screenshots and screen capture disabled")
    if initial["block_outgoing_calls"]:
        lines.append("All outgoing calls blocked")
    if initial["block_sms"]:
        lines.append("All SMS blocked")
    if initial["disallow_config_wifi"]:
        lines.append("Wi-Fi configuration locked")
    if initial["disallow_config_mobile_networks"]:
        lines.append("Mobile-network configuration locked")
    if initial["disallow_config_tethering"]:
        lines.append("Tethering configuration locked")
    if initial["disallow_config_vpn"]:
        lines.append("VPN configuration locked")
    if initial["blocked_domains"]:
        lines.append("DNS blocklist: " + ", ".join(initial["blocked_domains"].splitlines()))
    if initial["bedtime_start"] and initial["bedtime_end"]:
        lines.append(f"Bedtime {initial['bedtime_start']}–{initial['bedtime_end']} (end is exclusive)")
    if initial["bedtime_block_outgoing_calls"]:
        lines.append("Outgoing calls blocked during bedtime")
    if initial["bedtime_suspend_packages"]:
        lines.append("Apps suspended during bedtime: " + ", ".join(initial["bedtime_suspend_packages"].splitlines()))
    if initial["collection_desired"]:
        lines.append("Location collection desired (advisory only; the device switch still controls GPS)")
    if not lines:
        lines.append("No restrictions. Devices keep normal camera, calls, SMS, and apps.")
    return lines


def requires_publish_confirmation(document: dict | None) -> bool:
    initial = editor_initial(document)
    return any(
        (
            initial["suspend_packages"],
            initial["hide_packages"],
            initial["uninstall_blocked_packages"],
            initial["camera_disabled"],
            initial["screen_capture_disabled"],
            initial["block_outgoing_calls"],
            initial["block_sms"],
            initial["disallow_config_wifi"],
            initial["disallow_config_mobile_networks"],
            initial["disallow_config_tethering"],
            initial["disallow_config_vpn"],
            initial["blocked_domains"],
            initial["bedtime_start"],
            initial["bedtime_block_outgoing_calls"],
            initial["bedtime_suspend_packages"],
        )
    )
