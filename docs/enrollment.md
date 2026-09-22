# Enrollment

## Parent (Phase 1)

1. Owner/admin creates an `EnrollmentSession`.
2. Dashboard shows a one-time secret and QR JSON (`v`, `api_base`, `enrollment_session_id`, `enrollment_secret`).
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
