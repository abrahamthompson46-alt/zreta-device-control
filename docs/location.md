# Location (Phase 3)

Phase 3 implementation and automated verification complete. Physical-device verification is pending and must be completed before production release.

Location is consent-based, parent-enabled, and on-device disclosed. It is not covert tracking.

## What is collected

Latitude, longitude, horizontal accuracy, capture time, server receipt time, source (`fused` / `gps` / `network` / `unknown`), mock flag, and a device-generated `client_event_id`.

Not collected: speed, bearing, SSID, street address, movement traces, IMEI, Android ID, serial.

## Consent chain

1. Owner/admin enables `location_collection_enabled` (default **false**).
2. Device shows `LocationDisclosureActivity` and the user accepts.
3. Android runtime location permission (not `DevicePolicyManager.setPermissionGrantState`).
4. `LocationWorker` takes a one-shot fused fix about every 15 minutes and uploads with the Phase 2 device JWT.

If the parent disables location, new uploads are rejected with `disabled`. Ordinary unmanaged installs stay unmanaged; Device Owner is not required for location.

## APIs

Device (Bearer device JWT): `POST /api/v1/device/location`

Parent (session, **owner/admin only**; viewer **403**):

- `POST /api/v1/devices/{id}/location/enable`
- `POST /api/v1/devices/{id}/location/disable`
- `GET /api/v1/devices/{id}/location/latest`
- `GET /api/v1/devices/{id}/location/history`

`GET /api/v1/device/me` and heartbeat responses include `location_collection_enabled`. Heartbeat never includes coordinates.

## Limits

- Batch max 20
- 12 accepted points per device per rolling hour
- Capture timestamp skew: 15 minutes future, 24 hours past
- History retention: `LOCATION_RETENTION_DAYS` (default 30)
- Idempotency: unique `(device, client_event_id)`

## Dashboard

Owner/admin device detail shows latest coordinates, accuracy, timestamp, mock flag, and an OpenStreetMap link. No embedded map.

## Retention

`python manage.py purge_location_records`

## Audit

`location.enabled`, `location.disabled`, `location.accepted`, `location.rejected`. Coordinates are never stored in audit snapshots or application logs. Location views are not audited.

## Not in Phase 3

Geofencing, locate-now, live streaming, SOS, wipe/kiosk, always-on VPN, UsageStats daily limits.
