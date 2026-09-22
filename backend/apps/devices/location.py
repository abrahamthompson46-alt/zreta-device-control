from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.audit.services import record_audit
from apps.devices.crypto import DeviceAuthError
from apps.devices.models import Device, LocationRecord, LocationSource
from apps.devices.services import EnrollmentError

LOCATION_SOURCES = {choice.value for choice in LocationSource}


class LocationError(Exception):
    def __init__(self, message: str, code: str = "invalid"):
        super().__init__(message)
        self.code = code


def _parse_uuid(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _parse_captured_at(value):
    if not value:
        return None
    parsed = parse_datetime(str(value))
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.utc)
    return parsed


def _parse_coordinate(value, minimum: float, maximum: float):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if number < Decimal(str(minimum)) or number > Decimal(str(maximum)):
        return None
    return number.quantize(Decimal("0.000001"))


def _parse_accuracy(value):
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise LocationError("accuracy_m is invalid.", "invalid_accuracy") from None
    if number < 0 or number > 100000:
        raise LocationError("accuracy_m is out of range.", "invalid_accuracy")
    return number


def set_location_collection(*, device: Device, enabled: bool, actor_user, request_meta: dict | None = None) -> Device:
    meta = request_meta or {}
    with transaction.atomic():
        locked = Device.objects.select_for_update().get(pk=device.pk)
        if not locked.is_active and enabled:
            raise EnrollmentError("Revoked devices cannot enable location.", "revoked")
        previous = locked.location_collection_enabled
        locked.location_collection_enabled = bool(enabled)
        locked.save(update_fields=["location_collection_enabled", "updated_at"])
        record_audit(
            organization=locked.organization,
            actor_user=actor_user,
            target_device=locked,
            action="location.enabled" if enabled else "location.disabled",
            result="success",
            old_snapshot={"location_collection_enabled": previous},
            new_snapshot={"location_collection_enabled": locked.location_collection_enabled, "device_id": str(locked.id)},
            **meta,
        )
    return locked


def serialize_location(record: LocationRecord | None) -> dict | None:
    if record is None:
        return None
    return {
        "id": str(record.id),
        "captured_at": record.captured_at,
        "received_at": record.received_at,
        "latitude": str(record.latitude),
        "longitude": str(record.longitude),
        "accuracy_m": record.accuracy_m,
        "source": record.source,
        "is_mock": record.is_mock,
        "osm_url": (
            f"https://www.openstreetmap.org/?mlat={record.latitude}&mlon={record.longitude}"
            f"#map=16/{record.latitude}/{record.longitude}"
        ),
    }


def latest_location(device: Device) -> LocationRecord | None:
    status = getattr(device, "status", None)
    if status is not None and status.last_location_id:
        return status.last_location
    return device.location_records.order_by("-captured_at").first()


def location_history(device: Device, *, since=None, until=None, limit: int = 200):
    qs = device.location_records.all().order_by("-captured_at")
    if since:
        qs = qs.filter(captured_at__gte=since)
    if until:
        qs = qs.filter(captured_at__lte=until)
    cap = max(1, min(int(limit), settings.LOCATION_HISTORY_MAX))
    return list(qs[:cap])


def _validate_point(raw: dict, now) -> dict:
    if not isinstance(raw, dict):
        raise LocationError("Location item must be an object.", "invalid")
    if not raw.get("location_disclosure_accepted"):
        raise LocationError("Location disclosure must be accepted.", "disclosure_required")
    event_id = _parse_uuid(raw.get("client_event_id"))
    if event_id is None:
        raise LocationError("client_event_id is required.", "invalid_event_id")
    captured_at = _parse_captured_at(raw.get("captured_at"))
    if captured_at is None:
        raise LocationError("captured_at is required.", "invalid_timestamp")
    future = now + timedelta(seconds=settings.LOCATION_CAPTURE_FUTURE_SKEW_SECONDS)
    past = now - timedelta(seconds=settings.LOCATION_CAPTURE_PAST_SKEW_SECONDS)
    if captured_at > future or captured_at < past:
        raise LocationError("captured_at is outside the allowed window.", "invalid_timestamp")
    latitude = _parse_coordinate(raw.get("latitude"), -90, 90)
    longitude = _parse_coordinate(raw.get("longitude"), -180, 180)
    if latitude is None or longitude is None:
        raise LocationError("latitude and longitude must be valid coordinates.", "invalid_coordinates")
    accuracy = _parse_accuracy(raw.get("accuracy_m"))
    source = (raw.get("source") or LocationSource.UNKNOWN).strip().lower()
    if source not in LOCATION_SOURCES:
        source = LocationSource.UNKNOWN
    return {
        "client_event_id": event_id,
        "captured_at": captured_at,
        "latitude": latitude,
        "longitude": longitude,
        "accuracy_m": accuracy,
        "source": source,
        "is_mock": bool(raw.get("is_mock")),
    }


@transaction.atomic
def ingest_locations(*, device: Device, items: list, request_meta: dict | None = None) -> dict:
    meta = request_meta or {}
    locked = Device.objects.select_for_update().select_related("organization").get(pk=device.pk)
    if not locked.is_active:
        raise DeviceAuthError("Device is revoked.", "revoked")
    if not isinstance(items, list):
        raise LocationError("locations must be a list.", "invalid_batch")
    if len(items) == 0:
        raise LocationError("locations must not be empty.", "invalid_batch")
    if len(items) > settings.LOCATION_MAX_BATCH:
        raise LocationError("Too many location points in one request.", "invalid_batch")

    accepted: list[str] = []
    duplicates: list[str] = []
    rejected: list[dict] = []

    if not locked.location_collection_enabled:
        for raw in items:
            event_id = str(raw.get("client_event_id") or "") if isinstance(raw, dict) else ""
            rejected.append({"client_event_id": event_id, "code": "disabled"})
        record_audit(
            organization=locked.organization,
            actor_device=locked,
            target_device=locked,
            action="location.rejected",
            result="failure",
            new_snapshot={"device_id": str(locked.id), "code": "disabled", "count": len(rejected)},
            **meta,
        )
        status = locked.status
        status.location_last_error = "disabled"
        status.save(update_fields=["location_last_error", "updated_at"])
        return {"accepted": accepted, "duplicates": duplicates, "rejected": rejected}

    now = timezone.now()
    hour_ago = now - timedelta(hours=1)
    used_quota = LocationRecord.objects.filter(device=locked, received_at__gte=hour_ago).count()
    newest: LocationRecord | None = None

    for raw in items:
        try:
            point = _validate_point(raw, now)
        except LocationError as exc:
            event_id = ""
            if isinstance(raw, dict):
                event_id = str(raw.get("client_event_id") or "")
            rejected.append({"client_event_id": event_id, "code": exc.code})
            continue

        existing = LocationRecord.objects.filter(
            device=locked, client_event_id=point["client_event_id"]
        ).first()
        if existing is not None:
            duplicates.append(str(existing.client_event_id))
            if newest is None or existing.captured_at > newest.captured_at:
                newest = existing
            continue

        if used_quota >= settings.LOCATION_MAX_PER_HOUR:
            rejected.append({"client_event_id": str(point["client_event_id"]), "code": "rate_limited"})
            continue

        try:
            with transaction.atomic():
                record = LocationRecord.objects.create(
                    organization=locked.organization,
                    device=locked,
                    client_event_id=point["client_event_id"],
                    captured_at=point["captured_at"],
                    latitude=point["latitude"],
                    longitude=point["longitude"],
                    accuracy_m=point["accuracy_m"],
                    source=point["source"],
                    is_mock=point["is_mock"],
                )
        except IntegrityError:
            existing = LocationRecord.objects.filter(
                device=locked, client_event_id=point["client_event_id"]
            ).first()
            if existing is not None:
                duplicates.append(str(existing.client_event_id))
                if newest is None or existing.captured_at > newest.captured_at:
                    newest = existing
            else:
                rejected.append({"client_event_id": str(point["client_event_id"]), "code": "conflict"})
            continue

        used_quota += 1
        accepted.append(str(record.client_event_id))
        if newest is None or record.captured_at >= newest.captured_at:
            newest = record

    status = locked.status
    if newest is not None:
        current = status.last_location
        if current is None or newest.captured_at >= current.captured_at:
            status.last_location = newest
        if locked.location_authorized_at is None and accepted:
            locked.location_authorized_at = now
            locked.save(update_fields=["location_authorized_at", "updated_at"])
        status.location_last_error = None
        status.save(update_fields=["last_location", "location_last_error", "updated_at"])
    elif rejected:
        status.location_last_error = rejected[0]["code"][:32]
        status.save(update_fields=["location_last_error", "updated_at"])

    if accepted:
        record_audit(
            organization=locked.organization,
            actor_device=locked,
            target_device=locked,
            action="location.accepted",
            result="success",
            new_snapshot={
                "device_id": str(locked.id),
                "accepted_count": len(accepted),
                "duplicate_count": len(duplicates),
            },
            **meta,
        )
    if rejected:
        record_audit(
            organization=locked.organization,
            actor_device=locked,
            target_device=locked,
            action="location.rejected",
            result="failure",
            new_snapshot={
                "device_id": str(locked.id),
                "codes": sorted({item["code"] for item in rejected}),
                "rejected_count": len(rejected),
            },
            **meta,
        )
    return {"accepted": accepted, "duplicates": duplicates, "rejected": rejected}


def purge_expired_locations() -> int:
    cutoff = timezone.now() - timedelta(days=settings.LOCATION_RETENTION_DAYS)
    expired_ids = list(LocationRecord.objects.filter(captured_at__lt=cutoff).values_list("id", flat=True))
    if not expired_ids:
        return 0
    from apps.devices.models import DeviceStatus

    affected_ids = list(
        DeviceStatus.objects.filter(last_location_id__in=expired_ids).values_list("device_id", flat=True)
    )
    DeviceStatus.objects.filter(last_location_id__in=expired_ids).update(last_location=None)
    deleted, _ = LocationRecord.objects.filter(id__in=expired_ids).delete()
    for status in DeviceStatus.objects.filter(device_id__in=affected_ids).select_related("device"):
        latest = LocationRecord.objects.filter(device=status.device).order_by("-captured_at").first()
        if latest is not None:
            status.last_location = latest
            status.save(update_fields=["last_location", "updated_at"])
    return deleted
