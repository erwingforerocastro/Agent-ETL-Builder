"""Strict path-component validation for profiling artifacts."""

from __future__ import annotations

import re
from typing import Final

from domain.errors import ProfilingError

_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_MAX_COMPONENT_LENGTH: Final[int] = 100
_WINDOWS_RESERVED: Final[frozenset[str]] = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }
)


def safe_component(value: str, field_name: str) -> str:
    """Return a path-safe component or raise a structured profiling error."""
    text = value.strip()
    stem = text.split(".", 1)[0].upper()
    if (
        text != value
        or not _SAFE_COMPONENT.fullmatch(text)
        or len(text) > _MAX_COMPONENT_LENGTH
        or text.endswith(".")
        or stem in _WINDOWS_RESERVED
    ):
        raise ProfilingError(
            code="PROFILE_ARTIFACT_PATH_INVALID",
            message="Profiling artifact path contains an unsafe identifier",
            module=__name__,
            context={"field": field_name},
        )
    return text


__all__ = ["safe_component"]
