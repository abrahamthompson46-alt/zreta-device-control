# Enrollment

## Parent (Phase 1)

1. Owner/admin creates an `EnrollmentSession`.
2. Dashboard shows a one-time secret, a **PNG enrollment QR**, and the **exact canonical JSON** also encoded in that QR (`v`, `api_base`, `enrollment_session_id`, `enrollment_secret`). Paste and scan use the same bytes.
3. Only HMAC-SHA256 of the secret is stored.

## Device (Phase 2)

1. Device is provisioned as Device Owner (QR/AFW/zero-touch **or** lab `dpm set-device-owner`) **or** remains unmanaged (status will say so).
2. User scans/pastes enrollment JSON and accepts the disclosure screen.
3. App generates EC P-256 in Android Keystore (`zreta_device_identity`). Private key stays in Keystore.
4. `POST /api/v1/device/enroll` with public PEM + session secret.
5. Server atomically consumes the session, creates `Device` + `DeviceCredential`, returns a 15-minute access token.
6. App stores device id / token in EncryptedSharedPreferences (not plaintext SharedPreferences).
7. WorkManager heartbeat every 15 minutes; token refresh via ES256 assertion (`POST /api/v1/device/token`). Replay of `jti` is rejected.

**Product limitation:** an ordinary installation of the Android application on an already-configured phone does not make the phone Device Owner.

## Device Owner setup QR

Separate from the enrollment QR. After a factory reset, tap the welcome screen six times and scan the setup QR. Android downloads `GET /dpc.apk` (no login; the file contains no enrollment secret) and sets this app as Device Owner. The QR's admin extras carry the same one-time `api_base`, session id, and secret. The server computes signature and package checksums from `DPC_APK_PATH`. If that file is missing, the dashboard explains that the setup QR is unavailable.
