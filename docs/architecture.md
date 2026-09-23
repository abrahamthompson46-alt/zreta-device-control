# Architecture

Parent/Admin browser
        |
        | session cookie + CSRF
        v
Django dashboard + `/api/v1/` parent routes
        |
        v
PostgreSQL

Managed Android DPC  --HTTPS (or documented local cleartext)--  `/api/v1/device/*`
        |
        Keystore private key (never uploaded)
        EncryptedSharedPreferences (access token)

## Phase 2 apps

Unchanged Django apps. Additive device endpoints live in `apps.devices.device_api`.

Phase 4.1–4.8 cover policy models, lifecycle, parent APIs, device pull/ack, Android LKG cache, dashboard assign/publish, and Device Owner enforcement for applications/device/calls/internet/screen-time bedtime plus an advisory location adapter — see [policy-schema.md](policy-schema.md) and [api.md](api.md). Phase 6 adds FCM policy wake and PolicySchedule (server-side scheduled publish). **NOT IMPLEMENTED:** wipe/kiosk, always-on VPN, UsageStats daily limits.

## Device authentication

- Identity key: Android Keystore EC P-256, ES256 client assertions.
- Server stores PEM public key on `DeviceCredential`.
- Access tokens: HS256 JWT, audience `zreta-device`, TTL 900s, `token_use=device_access`.
- Revoke device → credentials `revoked` → token and assertion fail.
- Assertion `jti` uniqueness: `DeviceAssertionJti`.

## Heartbeat

WorkManager 15 minutes. Updates `DeviceStatus`. No location coordinates.

## Location (Phase 3)

Separate `POST /api/v1/device/location` using the Phase 2 device JWT. `location_collection_enabled` is additive on `/device/me` and heartbeat **responses**. Collection uses WorkManager + one-shot fused location after on-device disclosure and OS permission. Owner/admin dashboard only. See [location.md](location.md).

## FCM

Data-only **policy wake** (not an authoritative command channel). Devices register tokens via `POST /api/v1/device/fcm-token`. On policy publish (including scheduled publish), the backend may send FCM data `{type: policy_wake}` when `FIREBASE_CREDENTIALS_JSON` or `FIREBASE_CREDENTIALS_FILE` is set. The Android app enqueues `PolicyWorker`, which still pulls policy from the Django API. Without Firebase credentials, publish succeeds and wake is skipped.
