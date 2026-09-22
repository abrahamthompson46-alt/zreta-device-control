from .base import *  # noqa: F403

DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Prefer the local Postgres instance. SQLite is only for machines where Docker/Postgres
# credentials are unavailable (see docs/runbooks/local-development.md).
if env_bool("ZRETA_TEST_SQLITE", False):  # noqa: F405
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "test.sqlite3",  # noqa: F405
        }
    }
else:
    DATABASES["default"]["TEST"] = {"NAME": env("POSTGRES_TEST_DB", "test_zreta_control")}  # noqa: F405
