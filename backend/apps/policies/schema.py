from __future__ import annotations

"""Policy document schema v1 validation (Phase 4.2 + 4.7–4.8 section fields).

Publication rejects unknown top-level keys. Section bodies are objects.
Phase 4.7/4.8 add optional validated fields under applications, device, calls,
internet, screen_time, and location; empty section objects remain valid and
mean no enforcement.
"""

import re

from django.conf import settings

from apps.policies.exceptions import PolicyError

SCHEMA_VERSION_V1 = 1
SUPPORTED_SCHEMA_VERSIONS = frozenset({SCHEMA_VERSION_V1})

REQUIRED_SECTIONS = (
    "internet",
    "calls",
    "applications",
    "screen_time",
    "device",
    "location",
)

REQUIRED_TOP_LEVEL_KEYS = frozenset({"schema_version", *REQUIRED_SECTIONS})

APPLICATIONS_ALLOWED_KEYS = frozenset(
    {
        "suspend_packages",
        "hide_packages",
        "uninstall_blocked_packages",
    }
)
DEVICE_ALLOWED_KEYS = frozenset(
    {
        "camera_disabled",
        "screen_capture_disabled",
    }
)
CALLS_ALLOWED_KEYS = frozenset(
    {
        "block_outgoing_calls",
        "block_sms",
    }
)
INTERNET_ALLOWED_KEYS = frozenset(
    {
        "disallow_config_wifi",
        "disallow_config_mobile_networks",
        "disallow_config_tethering",
        "disallow_config_vpn",
        "traffic",
    }
)
TRAFFIC_ALLOWED_KEYS = frozenset(
    {
        "enabled",
        "engine",
        "blocked_domains",
    }
)
TRAFFIC_ENGINE_LOCAL_DNS_BLOCKLIST = "local_dns_blocklist"
TRAFFIC_MAX_DOMAINS = 500
TRAFFIC_MAX_DOMAIN_LENGTH = 253
TRAFFIC_MAX_TOTAL_CHARS = 8192
# Hostname labels: LDH, 1–63 chars; FQDN with ≥2 labels (no wildcards, no IPs).
_DOMAIN_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_IPV4_RE = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")
SCREEN_TIME_ALLOWED_KEYS = frozenset(
    {
        "bedtime_start",
        "bedtime_end",
        "bedtime_block_outgoing_calls",
        "bedtime_suspend_packages",
    }
)
LOCATION_ALLOWED_KEYS = frozenset(
    {
        "collection_desired",
    }
)

# Android package name: segments of [A-Za-z_][A-Za-z0-9_]* separated by dots.
_PACKAGE_NAME_RE = re.compile(
    r"^(?:[A-Za-z_][A-Za-z0-9_]*)(?:\.[A-Za-z_][A-Za-z0-9_]*)+$"
)
_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def empty_policy_document(*, schema_version: int = SCHEMA_VERSION_V1) -> dict:
    """Return a valid empty schema v1 document."""
    return {
        "schema_version": schema_version,
        "internet": {},
        "calls": {},
        "applications": {},
        "screen_time": {},
        "device": {},
        "location": {},
    }


def _validate_package_list(section: str, field: str, value) -> list[str]:
    if not isinstance(value, list) or isinstance(value, bool):
        raise PolicyError(
            f"Policy section '{section}.{field}' must be an array of package names.",
            "invalid_section_field",
        )
    packages: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str) or isinstance(item, bool):
            raise PolicyError(
                f"Policy section '{section}.{field}' entries must be strings.",
                "invalid_package_name",
            )
        name = item.strip()
        if not name or not _PACKAGE_NAME_RE.fullmatch(name):
            raise PolicyError(
                f"Invalid package name in '{section}.{field}'.",
                "invalid_package_name",
            )
        if name in seen:
            continue
        seen.add(name)
        packages.append(name)
    return packages


def _validate_optional_bool(section: str, field: str, value) -> bool:
    if type(value) is not bool:
        raise PolicyError(
            f"Policy section '{section}.{field}' must be a boolean.",
            "invalid_section_field",
        )
    return value


def _validate_hhmm(section: str, field: str, value) -> str:
    if not isinstance(value, str) or isinstance(value, bool):
        raise PolicyError(
            f"Policy section '{section}.{field}' must be an HH:MM string.",
            "invalid_section_field",
        )
    text = value.strip()
    if not _HHMM_RE.fullmatch(text):
        raise PolicyError(
            f"Policy section '{section}.{field}' must be HH:MM (00:00–23:59).",
            "invalid_section_field",
        )
    return text


def _validate_applications_section(section: dict) -> dict:
    unknown = set(section.keys()) - APPLICATIONS_ALLOWED_KEYS
    if unknown:
        raise PolicyError(
            f"Unknown applications keys: {', '.join(sorted(unknown))}.",
            "unknown_section_keys",
        )
    out: dict = {}
    for field in ("suspend_packages", "hide_packages", "uninstall_blocked_packages"):
        if field not in section:
            continue
        out[field] = _validate_package_list("applications", field, section[field])
    return out


def _validate_device_section(section: dict) -> dict:
    unknown = set(section.keys()) - DEVICE_ALLOWED_KEYS
    if unknown:
        raise PolicyError(
            f"Unknown device keys: {', '.join(sorted(unknown))}.",
            "unknown_section_keys",
        )
    out: dict = {}
    for field in ("camera_disabled", "screen_capture_disabled"):
        if field not in section:
            continue
        out[field] = _validate_optional_bool("device", field, section[field])
    return out


def _validate_calls_section(section: dict) -> dict:
    unknown = set(section.keys()) - CALLS_ALLOWED_KEYS
    if unknown:
        raise PolicyError(
            f"Unknown calls keys: {', '.join(sorted(unknown))}.",
            "unknown_section_keys",
        )
    out: dict = {}
    for field in ("block_outgoing_calls", "block_sms"):
        if field not in section:
            continue
        out[field] = _validate_optional_bool("calls", field, section[field])
    return out


def _normalize_block_domain(raw: str) -> str:
    if not isinstance(raw, str) or isinstance(raw, bool):
        raise PolicyError(
            "Policy section 'internet.traffic.blocked_domains' entries must be strings.",
            "invalid_domain",
        )
    text = raw.strip().lower()
    if text.endswith("."):
        text = text[:-1]
    return text


def _is_valid_block_domain(domain: str) -> bool:
    if not domain or len(domain) > TRAFFIC_MAX_DOMAIN_LENGTH:
        return False
    if "://" in domain or "/" in domain or ":" in domain or " " in domain or "*" in domain:
        return False
    if _IPV4_RE.fullmatch(domain):
        return False
    if ":" in domain:  # IPv6 or host:port (colon already caught); keep explicit
        return False
    labels = domain.split(".")
    if len(labels) < 2:
        return False
    for label in labels:
        if not label or len(label) > 63 or not _DOMAIN_LABEL_RE.fullmatch(label):
            return False
    return True


def _validate_blocked_domains(value) -> list[str]:
    if not isinstance(value, list) or isinstance(value, bool):
        raise PolicyError(
            "Policy section 'internet.traffic.blocked_domains' must be an array of domain strings.",
            "invalid_section_field",
        )
    if len(value) > TRAFFIC_MAX_DOMAINS:
        raise PolicyError(
            f"internet.traffic.blocked_domains exceeds maximum of {TRAFFIC_MAX_DOMAINS} entries.",
            "invalid_section_field",
        )
    out: list[str] = []
    seen: set[str] = set()
    total_chars = 0
    for item in value:
        domain = _normalize_block_domain(item)
        if not _is_valid_block_domain(domain):
            raise PolicyError(
                "Invalid domain in 'internet.traffic.blocked_domains'.",
                "invalid_domain",
            )
        if domain in seen:
            continue
        seen.add(domain)
        total_chars += len(domain)
        if total_chars > TRAFFIC_MAX_TOTAL_CHARS:
            raise PolicyError(
                f"internet.traffic.blocked_domains exceeds maximum total size of {TRAFFIC_MAX_TOTAL_CHARS} characters.",
                "invalid_section_field",
            )
        out.append(domain)
    out.sort()
    return out


def _validate_traffic_section(section: dict) -> dict:
    unknown = set(section.keys()) - TRAFFIC_ALLOWED_KEYS
    if unknown:
        raise PolicyError(
            f"Unknown internet.traffic keys: {', '.join(sorted(unknown))}.",
            "unknown_section_keys",
        )
    out: dict = {}
    if "enabled" in section:
        out["enabled"] = _validate_optional_bool("internet.traffic", "enabled", section["enabled"])
    if "engine" in section:
        engine = section["engine"]
        if not isinstance(engine, str) or isinstance(engine, bool):
            raise PolicyError(
                "Policy section 'internet.traffic.engine' must be a string.",
                "invalid_section_field",
            )
        if engine != TRAFFIC_ENGINE_LOCAL_DNS_BLOCKLIST:
            raise PolicyError(
                "Policy section 'internet.traffic.engine' must be 'local_dns_blocklist'.",
                "invalid_section_field",
            )
        out["engine"] = engine
    if "blocked_domains" in section:
        out["blocked_domains"] = _validate_blocked_domains(section["blocked_domains"])
    if out.get("enabled") is True or "blocked_domains" in out:
        out.setdefault("engine", TRAFFIC_ENGINE_LOCAL_DNS_BLOCKLIST)
    return out


def _validate_internet_section(section: dict) -> dict:
    unknown = set(section.keys()) - INTERNET_ALLOWED_KEYS
    if unknown:
        raise PolicyError(
            f"Unknown internet keys: {', '.join(sorted(unknown))}.",
            "unknown_section_keys",
        )
    out: dict = {}
    for field in (
        "disallow_config_wifi",
        "disallow_config_mobile_networks",
        "disallow_config_tethering",
        "disallow_config_vpn",
    ):
        if field not in section:
            continue
        out[field] = _validate_optional_bool("internet", field, section[field])
    if "traffic" in section:
        traffic = section["traffic"]
        if not isinstance(traffic, dict) or isinstance(traffic, bool):
            raise PolicyError(
                "Policy section 'internet.traffic' must be an object.",
                "invalid_section_field",
            )
        out["traffic"] = _validate_traffic_section(traffic)
    return out


def _validate_screen_time_section(section: dict) -> dict:
    unknown = set(section.keys()) - SCREEN_TIME_ALLOWED_KEYS
    if unknown:
        raise PolicyError(
            f"Unknown screen_time keys: {', '.join(sorted(unknown))}.",
            "unknown_section_keys",
        )
    out: dict = {}
    has_start = "bedtime_start" in section
    has_end = "bedtime_end" in section
    if has_start != has_end:
        raise PolicyError(
            "Policy section 'screen_time' requires both bedtime_start and bedtime_end.",
            "invalid_section_field",
        )
    if has_start:
        out["bedtime_start"] = _validate_hhmm("screen_time", "bedtime_start", section["bedtime_start"])
        out["bedtime_end"] = _validate_hhmm("screen_time", "bedtime_end", section["bedtime_end"])
        if out["bedtime_start"] == out["bedtime_end"]:
            raise PolicyError(
                "Policy section 'screen_time' bedtime_start and bedtime_end must differ.",
                "invalid_section_field",
            )
    if "bedtime_block_outgoing_calls" in section:
        if not has_start:
            raise PolicyError(
                "Policy section 'screen_time.bedtime_block_outgoing_calls' requires a bedtime window.",
                "invalid_section_field",
            )
        out["bedtime_block_outgoing_calls"] = _validate_optional_bool(
            "screen_time", "bedtime_block_outgoing_calls", section["bedtime_block_outgoing_calls"]
        )
    if "bedtime_suspend_packages" in section:
        if not has_start:
            raise PolicyError(
                "Policy section 'screen_time.bedtime_suspend_packages' requires a bedtime window.",
                "invalid_section_field",
            )
        out["bedtime_suspend_packages"] = _validate_package_list(
            "screen_time", "bedtime_suspend_packages", section["bedtime_suspend_packages"]
        )
    return out


def _validate_location_section(section: dict) -> dict:
    unknown = set(section.keys()) - LOCATION_ALLOWED_KEYS
    if unknown:
        raise PolicyError(
            f"Unknown location keys: {', '.join(sorted(unknown))}.",
            "unknown_section_keys",
        )
    out: dict = {}
    if "collection_desired" in section:
        out["collection_desired"] = _validate_optional_bool(
            "location", "collection_desired", section["collection_desired"]
        )
    return out


def validate_policy_document(document) -> dict:
    """Validate a publishable policy document.

    Returns a shallow-copied dict with validated section bodies.
    Does not mutate the caller's object.
    """
    if not isinstance(document, dict):
        raise PolicyError("Policy document must be a JSON object.", "invalid_document")

    max_bytes = int(getattr(settings, "POLICY_DOCUMENT_MAX_BYTES", 65536))
    from apps.policies.canonical import serialized_document_bytes

    raw = serialized_document_bytes(document)
    if len(raw) > max_bytes:
        raise PolicyError(
            f"Policy document exceeds maximum size of {max_bytes} bytes.",
            "document_too_large",
        )

    keys = set(document.keys())
    unknown = keys - REQUIRED_TOP_LEVEL_KEYS
    if unknown:
        raise PolicyError(
            f"Unknown top-level policy keys: {', '.join(sorted(unknown))}.",
            "unknown_keys",
        )

    missing = REQUIRED_TOP_LEVEL_KEYS - keys
    if missing:
        raise PolicyError(
            f"Missing required top-level policy keys: {', '.join(sorted(missing))}.",
            "missing_keys",
        )

    schema_version = document.get("schema_version")
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise PolicyError("schema_version must be an integer.", "invalid_schema_version")
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise PolicyError(
            f"Unsupported schema_version {schema_version}.",
            "unsupported_schema_version",
        )

    validated: dict = {"schema_version": schema_version}
    for section in REQUIRED_SECTIONS:
        value = document[section]
        if not isinstance(value, dict) or isinstance(value, bool):
            raise PolicyError(
                f"Policy section '{section}' must be an object.",
                "invalid_section_type",
            )
        if section == "applications":
            validated[section] = _validate_applications_section(value)
        elif section == "device":
            validated[section] = _validate_device_section(value)
        elif section == "calls":
            validated[section] = _validate_calls_section(value)
        elif section == "internet":
            validated[section] = _validate_internet_section(value)
        elif section == "screen_time":
            validated[section] = _validate_screen_time_section(value)
        elif section == "location":
            validated[section] = _validate_location_section(value)
        else:
            validated[section] = dict(value)
    return validated
