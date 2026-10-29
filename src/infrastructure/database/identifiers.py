"""Shared PostgreSQL identifier validation."""

from __future__ import annotations

import re

_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MAX_IDENTIFIER_LENGTH = 63
_RESERVED_PREFIX = "pg_"


def validate_identifier(value: str, field_name: str) -> str:
    """Return a trimmed simple PostgreSQL identifier or raise ``ValueError``."""
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    text = value.strip()
    if len(text) > _MAX_IDENTIFIER_LENGTH or not _IDENTIFIER_PATTERN.fullmatch(text):
        raise ValueError(f"{field_name} must be a simple PostgreSQL identifier")
    if text.lower().startswith(_RESERVED_PREFIX):
        raise ValueError(f"{field_name} must not use the reserved pg_ prefix")
    return text


__all__ = ["validate_identifier"]
