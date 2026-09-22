# API `/api/v1/`

Parent/browser routes use Django session authentication and CSRF.

Device routes use Bearer access tokens (HS256, ~15 minutes) after enrollment. Devices prove Keystore key possession with ES256 `client_assertion` JWTs on `/device/token`.

## Parent auth

| Method | Path | Notes |
|---|---|---|
| POST | `/api/v1/auth/register` | Creates user + family org + owner membership |
| POST | `/api/v1/auth/login` | Session login |
| POST | `/api/v1/auth/logout` | |
| GET | `/api/v1/auth/me` | Current user + organization |

## Enrollments (parent)

| Method | Path | Notes |
|---|---|---|
| POST | `/api/v1/enrollments` | Owner/admin. Returns one-time `enrollment_secret` |
| GET | `/api/v1/enrollments/{id}` | Status only; **no secret** |
| POST | `/api/v1/enrollments/{id}/cancel` | Owner/admin |

## Devices (parent)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/devices` | Org-scoped |
| GET | `/api/v1/devices/{id}` | 404 if other org |
| PATCH | `/api/v1/devices/{id}` | `display_name` only |
| POST | `/api/v1/devices/{id}/revoke` | Revokes credentials; device tokens fail |
| POST | `/api/v1/devices/{id}/location/enable` | Owner/admin |
| POST | `/api/v1/devices/{id}/location/disable` | Owner/admin |
| GET | `/api/v1/devices/{id}/location/latest` | Owner/admin (viewer 403) |
| GET | `/api/v1/devices/{id}/location/history` | Owner/admin (viewer 403) |

## Policies (parent, Phase 4.3)

Session auth + CSRF. Organization from membership session — never from request `organization_id`. Owner/admin mutate; viewer read-only. Cross-tenant IDs return **404**.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/policies` | List org policies |
| POST | `/api/v1/policies` | Create policy + initial empty draft (`schema_version` 1) |
| GET | `/api/v1/policies/{id}` | Detail + current published metadata + assignment_count |
| PATCH | `/api/v1/policies/{id}` | Metadata: `name`, `description`, `archived` |
| GET | `/api/v1/policies/{id}/versions` | Version list (no document body) |
| POST | `/api/v1/policies/{id}/versions` | New draft; optional `document` or `source_version_id` |
| PATCH | `/api/v1/policies/{id}/versions/{vid}` | Edit draft `document` only |
| POST | `/api/v1/policies/{id}/versions/{vid}/publish` | Publish via lifecycle service |
| POST | `/api/v1/policies/{id}/versions/{vid}/rollback` | New published version copied from historical target |
| GET | `/api/v1/policies/assignments` | List device↔policy assignments |
| POST | `/api/v1/policies/assignments` | `device_id`, `policy_id`, optional `pinned_version_id` (must be published); 409 if device already assigned |
| PATCH | `/api/v1/policies/assignments/{id}` | Change policy and/or pinned version |
| DELETE | `/api/v1/policies/assignments/{id}` | Unassign |

Effective version for an assignment: pinned published version if set, else current published version of the policy (may be null if none published). Documents are not copied onto assignments.

## Device agent (Phase 2 + Phase 3 location + Phase 4.4 policy pull)

| Method | Path | Auth |
|---|---|---|
| POST | `/api/v1/device/enroll` | Enrollment session + secret + public key |
| POST | `/api/v1/device/token` | ES256 client assertion |
| POST | `/api/v1/device/heartbeat` | Bearer; response may include `location_collection_enabled`, `policy_version_number`, `policy_assignment_state` |
| GET | `/api/v1/device/me` | Bearer; includes location + policy assignment hints |
| POST | `/api/v1/device/location` | Bearer; batch of location points |
| GET | `/api/v1/device/policy` | Bearer; effective policy for authenticated device only; supports `If-None-Match` / `ETag` |
| POST | `/api/v1/device/policy/ack` | Bearer; applied/rejected acknowledgement (idempotent `client_event_id`) |

Enroll body: `enrollment_session_id`, `enrollment_secret`, `disclosure_accepted`, `public_key_id`, `public_key` (PEM SPKI), `management_mode`, inventory fields. **No private key.**

Token body: `device_id`, `public_key_id`, `client_assertion` (ES256 JWT, `aud=zreta-device`, unique `jti`, short `exp`).

Location body: `{ "locations": [ { client_event_id, captured_at, latitude, longitude, accuracy_m, source, is_mock, location_disclosure_accepted } ] }`. No coordinates on heartbeat.

Policy ack body: `{ policy_version_id, version_number, content_hash, applied_at, result, client_event_id }` where `result` is one of `applied`, `rejected_malformed`, `rejected_schema`, `cached_unchanged`.

## Not implemented

Command endpoints, locate-now, geofencing, FCM, PolicySchedule, wipe/kiosk, always-on VPN, UsageStats daily limits.
