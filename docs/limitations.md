# Limitations

- Device Owner cannot be applied by installing a normal app after setup wizard completion.
- Location requires parent enable, on-device disclosure, and OS permission. WorkManager delays possible. Fused Location needs Google Play services.
- Phase 3 does not implement geofencing, locate-now, live streaming, SOS, lock, or wipe.
- Phase 4 policy enforcement does not include FCM wake, PolicySchedule, wipe/kiosk, always-on VPN, or UsageStats daily screen limits. Location `collection_desired` in policy is advisory only; Phase 3 `location_collection_enabled` remains authoritative. Internet policy fields include Device Owner **configuration** restrictions and Phase 5.1 `internet.traffic` local DNS filtering (VpnService, fail-open, disclosed foreground notification, **not** always-on/lockdown). Filtering is best-effort classic UDP DNS only — it will **not** reliably block direct IP access, DoH, DoT, TCP DNS, hard-coded resolvers, app-private networking, system traffic, or traffic while the VPN is down / consent missing / after reboot until re-enforced. JVM tests do not prove physical TUN/DNS behavior. Physical-device validation is required before production use of filtering.
- FCM is not implemented; heartbeat and location use WorkManager (OEM delays possible).
- Phase 2 and Phase 3 implementation and automated verification complete. Physical-device verification is pending and must be completed before production release.
- Local HTTP is documented only for emulator/localhost; do not trust-all certificates.
- Do not deploy this tree to production as-is.
- Concurrent enrollment-token consume and concurrent location-idempotency tests require PostgreSQL.
