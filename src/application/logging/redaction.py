"""Secret and credential redaction for logs and error envelopes."""

from __future__ import annotations

import re
from collections.abc import Mapping

REDACTED = "[REDACTED]"

_SECRET_KEYS = frozenset(
    {
        "access_key",
        "api_key",
        "apikey",
        "authorization",
        "client_secret",
        "connection_string",
        "credential",
        "credentials",
        "database_url",
        "dsn",
        "password",
        "passwd",
        "private_key",
        "secret",
        "token",
    }
)

_URL_CREDENTIALS = re.compile(
    r"(?i)\b((?:https?|postgres(?:ql)?|mysql|mongodb)://)[^/\s:@]+:[^@\s]+@"
)
_BEARER = re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]+")
_ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|secret|token|api_key|apikey|authorization|dsn)"
    r"\s*[:=]\s*[^\s,;]+"
)


def _redact_text(value: str) -> str:
    redacted = _URL_CREDENTIALS.sub(r"\1***:***@", value)
    redacted = _BEARER.sub(r"\1 [REDACTED]", redacted)
    return _ASSIGNMENT.sub(r"\1=[REDACTED]", redacted)


def redact_value(value: object, *, key: str | None = None) -> object:
    """Return a copy of a JSON-like value with secrets removed."""
    if key is not None and key.lower() in _SECRET_KEYS:
        return REDACTED if value not in (None, "") else value
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, Mapping):
        return {
            str(item_key): redact_value(item, key=str(item_key)) for item_key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    return value


def redact_mapping(value: Mapping[str, object]) -> dict[str, object]:
    """Redact a mapping and return a plain dictionary."""
    return {str(key): redact_value(item, key=str(key)) for key, item in value.items()}


__all__ = ["REDACTED", "redact_mapping", "redact_value"]
