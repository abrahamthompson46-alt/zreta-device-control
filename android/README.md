# Zreta Device Control — Android DPC (Phase 2)

Consent-based Device Owner agent. This is **not** spyware and does **not** become Device Owner from a normal Play/sideload install on an already-set-up phone.

Phase 2 implementation and automated verification complete. Physical-device verification is pending and must be completed before production release.

Pending physical-device verification includes:

1. Device Owner provisioning
2. Disclosure/consent flow
3. Secure enrollment
4. Android Keystore identity
5. Device JWT issuance
6. Token storage
7. Heartbeat
8. One-time enrollment-secret consumption
9. Ordinary-install unmanaged behavior

Do not begin Phase 3 until that device verification is done.

## Toolchain

| Component | Version |
|---|---|
| Android Gradle Plugin | 8.10.1 |
| Gradle | 8.11.1 |
| Kotlin | 2.1.10 |
| compileSdk / targetSdk | 36 |
| minSdk | 26 (Android 8.0) |
| Java | 17 |

`.\gradlew.bat assembleDebug` and `.\gradlew.bat test` have passed. Physical-device verification is still pending.

## Build the APK

1. Install Android Studio (includes JDK 17 + SDK).
2. Copy `local.properties.example` to `local.properties` and set `sdk.dir`.
3. From `android/`:

```powershell
.\gradlew.bat assembleDebug
```

APK: `android/app/build/outputs/apk/debug/app-debug.apk`

If the Gradle wrapper JAR is missing, use Android Studio **Open** on the `android` folder (Studio generates the wrapper).

## Lab Device Owner (dedicated test device, no accounts)

Factory-reset recommended. Skip adding Google accounts.

```text
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb shell dpm set-device-owner com.zreta.devicecontrol/.dpc.ZretaDeviceAdminReceiver
```

Then open the app, scan or paste the Phase 1 enrollment JSON/QR, accept disclosure.

## QR provisioning (SUPPORTED WITH CONDITIONS)

Android 7+ setup wizard QR can include DPC component name, APK download URL, signature checksum, and `PROVISIONING_ADMIN_EXTRAS_BUNDLE` with `api_base`, `enrollment_session_id`, `enrollment_secret`. The dashboard QR from Phase 1 is the **enrollment bootstrap JSON**, not a full AFW factory QR. After Device Owner is set (ADB or AFW), scan that JSON.

## Ordinary install

The status screen will show unmanaged. That is correct.

## Heartbeat

WorkManager unique periodic work every **15 minutes**, exponential backoff on failure. Not guaranteed on every OEM.

## Location (Phase 3)

Off by default. A parent/admin enables collection; the device shows a separate disclosure, then the normal Android location permission. `LocationWorker` takes a one-shot fused fix about every 15 minutes. Device Owner is not required. Physical-device verification is still pending.

## FCM

Wake-only. Place `android/app/google-services.json` for Firebase (plugin applied only when that file exists). On `policy_wake` data messages, `ZretaFirebaseMessagingService` enqueues `PolicyWorker`. Token registration: `POST /api/v1/device/fcm-token` after heartbeat / token refresh. Authoritative state remains the Django API.

## Crypto

EC P-256 in Android Keystore, ES256 client assertions, server HS256 access tokens (15 minutes). Private key is not exported.
