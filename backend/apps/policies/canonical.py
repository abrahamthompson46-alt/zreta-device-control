from __future__ import annotations

"""Deterministic policy document canonicalization and hashing.

Canonical form (used everywhere for size checks and content_hash):
- Recursive key sorting via json.dumps(sort_keys=True)
- Compact separators (',' , ':')
- ensure_ascii=False
- UTF-8 encoding
- SHA-256 hex digest prefixed with ``sha256:``

Only the policy document JSON is hashed — never policy names, assignments,
or audit metadata.
"""

import hashlib
import json
from typing import Any


def canonicalize_document(document: dict) -> dict:
    """Return a deep structural copy with stable key ordering applied via round-trip."""
    # Round-trip through deterministic JSON so nested key order is stable when re-parsed.
    text = serialize_canonical_json(document)
    return json.loads(text)


def serialize_canonical_json(document: Any) -> str:
    """Serialize ``document`` to the canonical JSON string (UTF-8 code points as-is)."""
    return json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def serialized_document_bytes(document: Any) -> bytes:
    return serialize_canonical_json(document).encode("utf-8")


def content_hash_for_document(document: dict) -> str:
    digest = hashlib.sha256(serialized_document_bytes(document)).hexdigest()
    return f"sha256:{digest}"
