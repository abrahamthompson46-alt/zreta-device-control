"""Production settings.

Select this module explicitly:

    DJANGO_SETTINGS_MODULE=zreta_control.settings.production

Local development keeps using ``zreta_control.settings.local``. The WSGI and
ASGI entrypoints leave that local default in place so an unset settings module
does not suddenly boot production rules during development.
"""

import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403

DEVELOPMENT_SECRET_KEY = "unsafe-dev-only-change-me"
_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def _required_text(environ, name: str) -> str:
    raw = environ.get(name)
    if raw is None or not str(raw).strip():
        raise ImproperlyConfigured(f"{name} must be set for production.")
    return str(raw).strip()


def _csv(name: str, raw: str) -> list[str]:
    items = [part.strip() for part in str(raw).split(",") if part.strip()]
    if not items:
        raise ImproperlyConfigured(f"{name} must be set for production.")
    return items


def _refuse_enabled(environ, name: str) -> None:
    raw = environ.get(name)
    if raw is None or not str(raw).strip():
        return
    value = str(raw).strip().lower()
    if value in _TRUE_VALUES:
        raise ImproperlyConfigured(f"{name} must not be enabled in production.")
    if value not in _FALSE_VALUES:
        raise ImproperlyConfigured(f"{name} must be a boolean.")


def _require_secure_cookie(environ, name: str) -> bool:
    raw = environ.get(name)
    if raw is None or not str(raw).strip():
        return True
    value = str(raw).strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        raise ImproperlyConfigured(f"{name} must be enabled in production.")
    raise ImproperlyConfigured(f"{name} must be a boolean.")


def apply_production_settings(environ=None) -> dict:
    """Validate the process environment and return production overrides.

    The returned mapping never includes a reason to print secret values.
    Missing PostgreSQL settings raise instead of using local defaults or SQLite.
    """

    environ = os.environ if environ is None else environ
    secret = environ.get("DJANGO_SECRET_KEY")
    if secret is None or not str(secret).strip() or str(secret).strip() == DEVELOPMENT_SECRET_KEY:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY must be set to a value other than the development placeholder."
        )
    _refuse_enabled(environ, "DJANGO_DEBUG")
    hosts = _csv("DJANGO_ALLOWED_HOSTS", _required_text(environ, "DJANGO_ALLOWED_HOSTS"))
    origins = _csv("DJANGO_CSRF_TRUSTED_ORIGINS", _required_text(environ, "DJANGO_CSRF_TRUSTED_ORIGINS"))
    session_secure = _require_secure_cookie(environ, "DJANGO_SESSION_COOKIE_SECURE")
    csrf_secure = _require_secure_cookie(environ, "DJANGO_CSRF_COOKIE_SECURE")

    password = environ.get("POSTGRES_PASSWORD")
    if password is None or str(password) == "":
        raise ImproperlyConfigured("POSTGRES_PASSWORD must be set for production.")
    port = environ.get("POSTGRES_PORT")
    port = "5432" if port is None or not str(port).strip() else str(port).strip()

    return {
        "SECRET_KEY": str(secret).strip(),
        "DEBUG": False,
        "ALLOWED_HOSTS": hosts,
        "CSRF_TRUSTED_ORIGINS": origins,
        "SESSION_COOKIE_SECURE": session_secure,
        "CSRF_COOKIE_SECURE": csrf_secure,
        "DATABASES": {
            "default": {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": _required_text(environ, "POSTGRES_DB"),
                "USER": _required_text(environ, "POSTGRES_USER"),
                "PASSWORD": str(password),
                "HOST": _required_text(environ, "POSTGRES_HOST"),
                "PORT": port,
                "CONN_MAX_AGE": 60,
                "OPTIONS": {"connect_timeout": 5},
            }
        },
    }


def install(environ=None) -> dict:
    applied = apply_production_settings(environ)
    globals().update(applied)
    return applied


if os.environ.get("DJANGO_SETTINGS_MODULE") == "zreta_control.settings.production":
    install()
