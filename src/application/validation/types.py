"""Pure type matching for registry argument contracts."""

from __future__ import annotations


def value_matches_type(value: object, declared: str) -> bool:
    """Return whether a value satisfies a registry input type description."""
    alternatives = declared.split(" | ")
    if value is None:
        return "null" in alternatives

    return any(
        _value_matches_single_type(value, alternative)
        for alternative in alternatives
        if alternative != "null"
    )


def _value_matches_single_type(value: object, declared: str) -> bool:
    if declared == "string":
        return isinstance(value, str)
    if declared == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if declared == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if declared == "boolean":
        return isinstance(value, bool)
    if declared.startswith("enum[") and declared.endswith("]"):
        return isinstance(value, str) and value in declared[5:-1].split("|")
    if declared.startswith("array[") and declared.endswith("]"):
        item_type = declared[6:-1]
        return isinstance(value, list | tuple) and all(
            value_matches_type(item, item_type) for item in value
        )
    return False


__all__ = ["value_matches_type"]
