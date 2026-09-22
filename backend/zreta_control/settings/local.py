from .base import *  # noqa: F403

DEBUG = True

if env_bool("ZRETA_USE_SQLITE", False):  # noqa: F405
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "dev.sqlite3",  # noqa: F405
        }
    }
