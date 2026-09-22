# Local development

## Versions chosen

| Component | Version | Why |
|---|---|---|
| Python | 3.14.x (local) / requires >=3.12 | Verified on this machine |
| Django | 5.2 LTS (`>=5.2.17,<5.3`) | Security-supported through April 2028; not a pre-release |
| DRF | 3.16.x | Matches Django 5.2 |
| PostgreSQL | 16 (Docker) | Project database |
| QR | segno 1.6.x | Small library; QR payload only |

Redis and Celery are **not** started.

## Steps (Windows PowerShell)

From the repository root `p_control`:

1. Copy `.env.example` to `.env` and fill in random values for `DJANGO_SECRET_KEY`, `ENROLLMENT_TOKEN_PEPPER`, and `POSTGRES_PASSWORD`. Never commit `.env`.
2. Start Postgres:

```powershell
docker compose up -d db
```

3. Create a virtualenv and install:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\pip install -r requirements-dev.txt
```

4. Apply **local** migrations only:

```powershell
.\.venv\Scripts\python manage.py migrate
.\.venv\Scripts\python manage.py runserver
```

5. Open http://127.0.0.1:8000/register/

6. Tests:

```powershell
.\.venv\Scripts\pytest
```

Do not set `POSTGRES_HOST` to any production or existing Zreta database.

If Docker Engine is not running, you may set `ZRETA_USE_SQLITE=true` and `ZRETA_TEST_SQLITE=true` in `.env` so `runserver` and tests can use a local SQLite file. Phase 1 still targets PostgreSQL (see `docker-compose.yml`). Re-enable Postgres as soon as Docker or a dedicated local role is available. The concurrent enrollment-token test is skipped on SQLite.
