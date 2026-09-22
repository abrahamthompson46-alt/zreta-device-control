# Threat model

| Threat | Mitigation |
|---|---|
| Stolen enrollment QR | TTL, hashed secret, single-use, cancel |
| Cross-tenant enroll | Session bound to org; secret must match that session |
| Enrollment replay | Atomic consume; used/expired/cancelled rejected |
| Assertion replay | Unique `jti` in `DeviceAssertionJti` |
| Token theft | 15-minute access JWT; EncryptedSharedPreferences; revoke |
| Fake DPC | Must present matching Keystore-signed assertion after enroll; UUID is not auth |
| Private key exfil | Keystore; server rejects PRIVATE PEM; never logged |
| Insecure TLS | No trust-all; cleartext only emulator/localhost debug domains |
| Hidden enrollment | Explicit disclosure UI; Device Owner status shown honestly |
| Parent cookie as device | Device routes require device Bearer, not session user |
| Covert location | Default off; parent enable + on-device disclosure + OS permission; no DPM silent grant |
| Location API abuse | Device JWT, rate limit, batch cap, timestamp/coordinate checks, idempotent event ids |
| Cross-tenant location | Org-scoped queries; other org sees 404 |
| Viewer location access | Owner/admin only; viewer 403 |
| Location in logs | Audit and SafeLog redact coordinates |

