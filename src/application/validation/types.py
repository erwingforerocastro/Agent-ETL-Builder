"""Pure type matching for registry argument contracts."""

from __future__ import annotations


def value_matches_type(value: object, declared: str) -> bool:
    """Return whether a value satisfies a registry input type description."""
    if value is None:
        return declared == "null" or declared.endswith(" | null")

    base = declared.removesuffix(" | null")
    if base == "string":
        return isinstance(value, str)
    if base == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if base == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if base == "boolean":
        return isinstance(value, bool)
    if base.startswith("enum[") and base.endswith("]"):
        return isinstance(value, str) and value in base[5:-1].split("|")
    if base.startswith("array[") and base.endswith("]"):
        item_type = base[6:-1]
        return isinstance(value, list | tuple) and all(
            value_matches_type(item, item_type) for item in value
        )
    return False


__all__ = ["value_matches_type"]
