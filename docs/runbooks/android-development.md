# Android development (Phase 2)

## Toolchain chosen

Inspected 2026-09-19: no `JAVA_HOME`/`java` on PATH, no Android SDK (`ANDROID_HOME` unset, default `%LOCALAPPDATA%\Android\Sdk` missing). Versions below are current stable Android/Gradle, not a downgrade.

- AGP 8.10.2
- Gradle 8.11.1
- Kotlin 2.1.10
- compileSdk/targetSdk 36
- minSdk 26
- AndroidX AppCompat / WorkManager / Security Crypto / OkHttp 4.12

Install Android Studio, SDK Platform 36, build-tools, and a device/emulator.

## Local HTTP to Django

Do not disable TLS verification.

Emulator: set dashboard `PUBLIC_API_BASE_URL=http://10.0.2.2:8000` before creating the enrollment QR.

Physical device: `adb reverse tcp:8000 tcp:8000` and use `http://127.0.0.1:8000` in the QR, or HTTPS.

Release builds must use HTTPS. `network_security_config.xml` permits cleartext only for emulator/localhost domains.
