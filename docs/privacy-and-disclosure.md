# Privacy and disclosure (Phase 1)

Zreta Device Control is a consent-based management product.

- Enrollment is explicit: a parent creates a session and a device must present the one-time secret (Phase 2).
- Device Owner capabilities will be disclosed on-device during official Android provisioning.
- Location and phone numbers: Phase 3 collects location only after parent enable, on-device disclosure, and OS permission. Coordinates are never written raw into audit snapshots or application logs. Phone numbers are not collected.
- Audit logs omit passwords, enrollment secrets, tokens, private keys, and coordinates.
- Serial numbers are optional and not used for authentication.

**Disclosure copy used in the dashboard:**

> An ordinary installation of the Android application on an already-configured phone does not make the phone Device Owner.
