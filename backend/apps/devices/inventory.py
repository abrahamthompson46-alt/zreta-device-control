"""Replace a device's installed-app snapshot. Does not log package labels or names."""

from __future__ import annotations

import re

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.devices.models import InstalledApplication

_PACKAGE_NAME_RE = re.compile(r"^(?:[A-Za-z_][A-Za-z0-9_]*)(?:\.[A-Za-z_][A-Za-z0-9_]*)+$")
_MAX_VERSION_CODE = 2**63 - 1


class InventoryError(Exception):
    def __init__(self, message: str, code: str = "invalid"):
        super().__init__(message)
        self.code = code


def _require_package_name(value) -> str:
    if not isinstance(value, str) or isinstance(value, bool):
        raise InventoryError("package_name must be a string.", "invalid_package_name")
    name = value.strip()
    if not _PACKAGE_NAME_RE.fullmatch(name) or len(name) > 255:
        raise InventoryError("Invalid package name.", "invalid_package_name")
    return name


def _require_label(value) -> str:
    if not isinstance(value, str) or isinstance(value, bool):
        raise InventoryError("label must be a string.", "invalid_label")
    label = value.strip()
    if not label or len(label) > 150:
        raise InventoryError("label is required and must be at most 150 characters.", "invalid_label")
    return label


def _require_version_name(value) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) or isinstance(value, bool):
        raise InventoryError("version_name must be a string.", "invalid_version_name")
    text = value.strip()
    if len(text) > 64:
        raise InventoryError("version_name is too long.", "invalid_version_name")
    return text


def _require_version_code(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InventoryError("version_code must be an integer.", "invalid_version_code")
    if value < 0 or value > _MAX_VERSION_CODE:
        raise InventoryError("version_code is out of range.", "invalid_version_code")
    return value


def parse_inventory_apps(payload) -> tuple[list[dict], bool]:
    if not isinstance(payload, dict):
        raise InventoryError("Inventory body must be an object.", "invalid_inventory")
    if "complete" not in payload or type(payload.get("complete")) is not bool:
        raise InventoryError("complete must be a boolean.", "invalid_inventory")
    complete = payload["complete"]
    apps = payload.get("apps")
    if not isinstance(apps, list) or isinstance(apps, bool):
        raise InventoryError("apps must be an array.", "invalid_inventory")
    limit = int(getattr(settings, "INSTALLED_APP_MAX_BATCH", 400) or 400)
    if len(apps) > limit:
        raise InventoryError(f"apps exceeds the maximum of {limit}.", "inventory_too_large")
    parsed: list[dict] = []
    seen: set[str] = set()
    for item in apps:
        if not isinstance(item, dict):
            raise InventoryError("Each app entry must be an object.", "invalid_inventory")
        for field in ("package_name", "label", "version_code"):
            if field not in item:
                raise InventoryError(f"{field} is required.", "invalid_inventory")
        package_name = _require_package_name(item.get("package_name"))
        if package_name in seen:
            raise InventoryError("Duplicate package_name in inventory.", "invalid_package_name")
        seen.add(package_name)
        parsed.append(
            {
                "package_name": package_name,
                "label": _require_label(item.get("label")),
                "version_name": _require_version_name(item.get("version_name")),
                "version_code": _require_version_code(item.get("version_code")),
            }
        )
    return parsed, complete


@transaction.atomic
def replace_installed_inventory(*, device, apps: list[dict], complete: bool) -> dict:
    now = timezone.now()
    existing = {
        row.package_name: row
        for row in InstalledApplication.objects.select_for_update().filter(device=device)
    }
    reported = {item["package_name"] for item in apps}
    created = 0
    updated = 0
    for item in apps:
        row = existing.get(item["package_name"])
        if row is None:
            InstalledApplication.objects.create(
                organization=device.organization,
                device=device,
                package_name=item["package_name"],
                label=item["label"],
                version_name=item["version_name"],
                version_code=item["version_code"],
                first_seen=now,
                last_reported=now,
            )
            created += 1
            continue
        row.label = item["label"]
        row.version_name = item["version_name"]
        row.version_code = item["version_code"]
        row.last_reported = now
        row.removed_at = None
        row.save(
            update_fields=["label", "version_name", "version_code", "last_reported", "removed_at"]
        )
        updated += 1
    marked_removed = 0
    if complete:
        for package_name, row in existing.items():
            if package_name in reported or row.removed_at is not None:
                continue
            row.removed_at = now
            row.save(update_fields=["removed_at"])
            marked_removed += 1
    return {
        "reported": len(apps),
        "created": created,
        "updated": updated,
        "marked_removed": marked_removed,
        "complete": complete,
    }
