# Android feasibility (Phase 2)

**An ordinary installation of the Android application on an already-configured phone does not make the phone Device Owner.**

| Topic | Classification |
|---|---|
| Custom DPC + DeviceAdminReceiver | SUPPORTED |
| Detect Device Owner vs unmanaged | SUPPORTED |
| Lab ADB `dpm set-device-owner` | SUPPORTED WITH CONDITIONS (no accounts; test devices) |
| QR/AFW Device Owner during setup | SUPPORTED WITH CONDITIONS (factory reset / setup wizard; checksummed APK URL) |
| Silent promote to Device Owner after setup | NOT APPROPRIATE / NOT IMPLEMENTED |
| Android Keystore EC P-256 | SUPPORTED |
| WorkManager heartbeat | SUPPORTED WITH CONDITIONS (OEM battery managers may delay) |
| FCM wake | SUPPORTED WITH CONDITIONS (data-only wake → PolicyWorker pull; requires Firebase + google-services.json; not a command channel) |
| Location / internet / calls / app block / screen time / lock / wipe | Location: Phase 3 (consent + OS permission). Policy sections: Phase 4.7–4.8 Device Owner enforcement (apps/device/calls/internet/bedtime); location policy advisory only. Lock/wipe/VPN lockdown/UsageStats: NOT IMPLEMENTED |
| Covert persistence after factory reset | NOT APPROPRIATE |

Known platform limitation: Device Owner provisioning is a setup-time platform flow. This app cannot bypass it.
