"""Shared enum vocabularies for registry modules."""

from typing import Final

KEEP_POLICIES: Final[tuple[str, ...]] = ("first", "last")
COLUMN_CASES: Final[tuple[str, ...]] = ("lower", "upper", "preserve")
WHITESPACE_POLICIES: Final[tuple[str, ...]] = ("both", "leading", "trailing")
CAST_TARGET_TYPES: Final[tuple[str, ...]] = ("string", "integer", "float")
CAST_ERROR_MODES: Final[tuple[str, ...]] = ("raise", "coerce")
FILTER_OPERATORS: Final[tuple[str, ...]] = (
    "equals",
    "not_equals",
    "greater_than",
    "greater_or_equal",
    "less_than",
    "less_or_equal",
    "is_null",
    "is_not_null",
    "contains",
    "starts_with",
    "ends_with",
)
FILL_METHODS: Final[tuple[str, ...]] = ("constant", "mean", "median", "mode")
DATE_PARSE_MODES: Final[tuple[str, ...]] = ("raise", "coerce")
TEXT_CASES: Final[tuple[str, ...]] = ("lower", "upper", "title")

__all__ = [
    "CAST_ERROR_MODES",
    "CAST_TARGET_TYPES",
    "COLUMN_CASES",
    "DATE_PARSE_MODES",
    "FILL_METHODS",
    "FILTER_OPERATORS",
    "KEEP_POLICIES",
    "TEXT_CASES",
    "WHITESPACE_POLICIES",
]
