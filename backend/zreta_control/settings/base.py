import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
REPO_ROOT = BASE_DIR.parent
load_dotenv(REPO_ROOT / ".env")


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name, default)
    return value


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


SECRET_KEY = env("DJANGO_SECRET_KEY", "unsafe-dev-only-change-me")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = [
    host.strip()
    for host in (env("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost") or "").split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "apps.accounts.apps.AccountsConfig",
    "apps.devices.apps.DevicesConfig",
    "apps.policies.apps.PoliciesConfig",
    "apps.audit.apps.AuditConfig",
    "apps.dashboard.apps.DashboardConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.accounts.middleware.CurrentOrganizationMiddleware",
]

ROOT_URLCONF = "zreta_control.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.accounts.context_processors.current_organization",
            ],
        },
    }
]

WSGI_APPLICATION = "zreta_control.wsgi.application"
ASGI_APPLICATION = "zreta_control.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "zreta_control"),
        "USER": env("POSTGRES_USER", "zreta"),
        "PASSWORD": env("POSTGRES_PASSWORD", ""),
        "HOST": env("POSTGRES_HOST", "127.0.0.1"),
        "PORT": env("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
        "OPTIONS": {"connect_timeout": 5},
    }
}

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "dashboard:home"
LOGOUT_REDIRECT_URL = "accounts:login"

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = env_bool("DJANGO_SESSION_COOKIE_SECURE", False)
CSRF_COOKIE_HTTPONLY = False  # required for JS fetch of CSRF cookie if needed
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = env_bool("DJANGO_CSRF_COOKIE_SECURE", False)
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in (env("DJANGO_CSRF_TRUSTED_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000") or "").split(",")
    if origin.strip()
]

SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"

EMAIL_BACKEND = env("DJANGO_EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = env("DJANGO_DEFAULT_FROM_EMAIL", "noreply@localhost")

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
}

ENROLLMENT_TOKEN_PEPPER = env("ENROLLMENT_TOKEN_PEPPER", SECRET_KEY)
ENROLLMENT_SESSION_TTL_MINUTES = int(env("ENROLLMENT_SESSION_TTL_MINUTES", "30") or "30")
PUBLIC_API_BASE_URL = (env("PUBLIC_API_BASE_URL", "http://127.0.0.1:8000") or "http://127.0.0.1:8000").rstrip("/")

# Device authentication (Phase 2). Access tokens are short-lived HS256 JWTs.
# Long-term proof remains the Android Keystore key; the server stores only the public key.
DEVICE_ACCESS_TOKEN_TTL_SECONDS = int(env("DEVICE_ACCESS_TOKEN_TTL_SECONDS", "900") or "900")
DEVICE_ASSERTION_TTL_SECONDS = int(env("DEVICE_ASSERTION_TTL_SECONDS", "120") or "120")
DEVICE_JWT_AUDIENCE = env("DEVICE_JWT_AUDIENCE", "zreta-device") or "zreta-device"
DEVICE_JWT_ISSUER = env("DEVICE_JWT_ISSUER", "zreta-control") or "zreta-control"

# Location (Phase 3). Coordinates are never written to audit snapshots or application logs.
LOCATION_RETENTION_DAYS = int(env("LOCATION_RETENTION_DAYS", "30") or "30")
LOCATION_MAX_BATCH = int(env("LOCATION_MAX_BATCH", "20") or "20")
LOCATION_MAX_PER_HOUR = int(env("LOCATION_MAX_PER_HOUR", "12") or "12")
LOCATION_CAPTURE_FUTURE_SKEW_SECONDS = int(env("LOCATION_CAPTURE_FUTURE_SKEW_SECONDS", "900") or "900")
LOCATION_CAPTURE_PAST_SKEW_SECONDS = int(env("LOCATION_CAPTURE_PAST_SKEW_SECONDS", str(24 * 3600)) or str(24 * 3600))
LOCATION_HISTORY_MAX = int(env("LOCATION_HISTORY_MAX", "200") or "200")

# Policy documents (Phase 4.2). Validation/lifecycle only; no device pull or enforcement yet.
POLICY_DOCUMENT_MAX_BYTES = int(env("POLICY_DOCUMENT_MAX_BYTES", "65536") or "65536")
POLICY_SCHEMA_VERSION = 1

# MFA is not implemented in Phase 1. User.mfa_enabled exists as a future hook only.
MFA_ENABLED = False
