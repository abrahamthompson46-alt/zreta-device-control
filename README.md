# Zreta Device Control

Consent-based Android device-management and parental-control platform.

This repository is in **Phase 3**: Django backend + Kotlin DPC with enrollment, Keystore auth, heartbeat, and consent-based location.

Phase 2 and Phase 3 implementation and automated verification complete. Physical-device verification is pending and must be completed before production release.

Pending physical-device verification includes Phase 2 items plus location disclosure, OS permission, WorkManager fused fixes, and parent latest/history.

## What is implemented

- Phase 1 parent dashboard, org tenancy, hashed enrollment sessions, audit
- Android DPC with honest Device Owner vs unmanaged status
- Secure device enroll / token / heartbeat APIs
- Phase 3 location upload, owner/admin dashboard latest/history, 30-day retention

## What is not implemented

- Geofencing, locate-now, live streaming, SOS
- Internet, call, application, or screen-time controls
- FCM command channel
- Production deployment

**Product limitation:** an ordinary installation of the Android application on an already-configured phone does not make the phone Device Owner.

## Versions (Phase 1)

- Python 3.14 (local toolchain)
- Django 5.2 LTS (`>=5.2.17,<5.3`)
- Django REST Framework 3.16
- PostgreSQL 16
- segno (QR codes)

## Local development

See [docs/runbooks/local-development.md](docs/runbooks/local-development.md).

```powershell
copy .env.example .env
# Set DJANGO_SECRET_KEY, ENROLLMENT_TOKEN_PEPPER, POSTGRES_PASSWORD
docker compose up -d db
cd backend
python -m venv .venv
.\.venv\Scripts\pip install -r requirements-dev.txt
.\.venv\Scripts\python manage.py migrate
.\.venv\Scripts\python manage.py runserver
```

Open http://127.0.0.1:8000/register/

## Tests

```powershell
cd backend
.\.venv\Scripts\pytest
```

See [docs/runbooks/android-development.md](docs/runbooks/android-development.md) and [android/README.md](android/README.md).
