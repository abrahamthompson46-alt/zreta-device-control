from __future__ import annotations

import hashlib
import hmac
import secrets

from django.conf import settings


def generate_enrollment_secret() -> str:
    return secrets.token_urlsafe(32)


def hash_enrollment_secret(raw_secret: str) -> str:
    pepper = (settings.ENROLLMENT_TOKEN_PEPPER or settings.SECRET_KEY).encode()
    return hmac.new(pepper, raw_secret.encode(), hashlib.sha256).hexdigest()


def secrets_match(raw_secret: str, token_hash: str) -> bool:
    expected = hash_enrollment_secret(raw_secret)
    return hmac.compare_digest(expected, token_hash)
