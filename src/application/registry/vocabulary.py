"""Shared enum vocabularies for registry modules."""

from typing import Final

KEEP_POLICIES: Final[tuple[str, ...]] = ("first", "last")
COLUMN_CASES: Final[tuple[str, ...]] = ("lower", "upper", "preserve")
WHITESPACE_POLICIES: Final[tuple[str, ...]] = ("both", "leading", "trailing")
CAST_TARGET_TYPES: Final[tuple[str, ...]] = ("string", "integer", "float")
CAST_ERROR_MODES: Final[tuple[str, ...]] = ("raise", "coerce")

__all__ = [
    "CAST_ERROR_MODES",
    "CAST_TARGET_TYPES",
    "COLUMN_CASES",
    "KEEP_POLICIES",
    "WHITESPACE_POLICIES",
]
