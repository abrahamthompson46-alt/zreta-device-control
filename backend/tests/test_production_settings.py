import os

import pytest
from django.core.exceptions import ImproperlyConfigured

from zreta_control.settings.production import DEVELOPMENT_SECRET_KEY, apply_production_settings


def _valid(**overrides):
    values = {
        "DJANGO_SECRET_KEY": "test-only-production-secret",
        "DJANGO_DEBUG": "false",
        "DJANGO_ALLOWED_HOSTS": "control.zreta.com",
        "DJANGO_CSRF_TRUSTED_ORIGINS": "https://control.zreta.com",
        "DJANGO_SESSION_COOKIE_SECURE": "true",
        "DJANGO_CSRF_COOKIE_SECURE": "true",
        "POSTGRES_DB": "zreta_prod",
        "POSTGRES_USER": "zreta",
        "POSTGRES_PASSWORD": "test-only-database-password",
        "POSTGRES_HOST": "127.0.0.1",
        "POSTGRES_PORT": "5432",
        "ZRETA_USE_SQLITE": "true",
    }
    values.update(overrides)
    return values


def test_production_rejects_development_secret():
    with pytest.raises(ImproperlyConfigured):
        apply_production_settings(_valid(DJANGO_SECRET_KEY=DEVELOPMENT_SECRET_KEY))
    with pytest.raises(ImproperlyConfigured):
        missing = _valid()
        del missing["DJANGO_SECRET_KEY"]
        apply_production_settings(missing)


def test_production_debug_is_false_and_refuses_debug_enabled():
    applied = apply_production_settings(_valid())
    assert applied["DEBUG"] is False
    with pytest.raises(ImproperlyConfigured):
        apply_production_settings(_valid(DJANGO_DEBUG="true"))


def test_production_secure_cookies_default_on_and_reject_insecure():
    applied = apply_production_settings(_valid())
    assert applied["SESSION_COOKIE_SECURE"] is True
    assert applied["CSRF_COOKIE_SECURE"] is True
    omitted = _valid()
    del omitted["DJANGO_SESSION_COOKIE_SECURE"]
    del omitted["DJANGO_CSRF_COOKIE_SECURE"]
    cookies = apply_production_settings(omitted)
    assert cookies["SESSION_COOKIE_SECURE"] is True
    assert cookies["CSRF_COOKIE_SECURE"] is True
    with pytest.raises(ImproperlyConfigured):
        apply_production_settings(_valid(DJANGO_SESSION_COOKIE_SECURE="false"))
    with pytest.raises(ImproperlyConfigured):
        apply_production_settings(_valid(DJANGO_CSRF_COOKIE_SECURE="false"))


def test_production_requires_hosts_and_origins():
    for name in ("DJANGO_ALLOWED_HOSTS", "DJANGO_CSRF_TRUSTED_ORIGINS"):
        with pytest.raises(ImproperlyConfigured):
            missing = _valid()
            del missing[name]
            apply_production_settings(missing)
        with pytest.raises(ImproperlyConfigured):
            apply_production_settings(_valid(**{name: " , "}))


def test_production_uses_postgresql_not_sqlite():
    applied = apply_production_settings(_valid(ZRETA_USE_SQLITE="true"))
    engine = applied["DATABASES"]["default"]["ENGINE"]
    assert engine == "django.db.backends.postgresql"
    assert "sqlite" not in engine
    with pytest.raises(ImproperlyConfigured):
        missing = _valid()
        del missing["POSTGRES_DB"]
        apply_production_settings(missing)


def test_local_development_settings_still_enable_debug():
    from zreta_control.settings import local

    assert local.DEBUG is True
    engine = local.DATABASES["default"]["ENGINE"]
    flag = (os.environ.get("ZRETA_USE_SQLITE") or "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        assert engine.endswith("sqlite3")
    else:
        assert engine == "django.db.backends.postgresql"
