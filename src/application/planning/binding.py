"""Deterministic source and destination binding for natural-language plans."""

from __future__ import annotations

from pathlib import PurePosixPath

SOURCE_OPERATIONS: dict[str, str] = {
    ".csv": "read_csv",
    ".json": "read_json",
    ".jsonl": "read_jsonl",
    ".ndjson": "read_jsonl",
    ".parquet": "read_parquet",
    ".pq": "read_parquet",
}

DESTINATION_OPERATIONS: dict[str, str] = {
    ".csv": "save_csv",
    ".json": "save_json",
    ".jsonl": "save_jsonl",
    ".ndjson": "save_jsonl",
    ".parquet": "save_parquet",
    ".pq": "save_parquet",
}

SUPPORTED_SOURCE_SUFFIXES = tuple(sorted(SOURCE_OPERATIONS))
SUPPORTED_DESTINATION_SUFFIXES = tuple(sorted(DESTINATION_OPERATIONS))


def _suffix(path: str | None) -> str | None:
    if path is None or not path.strip():
        return None
    normalized = path.strip().replace("\\", "/")
    suffix = PurePosixPath(normalized).suffix.lower()
    return suffix or None


def source_operation_for_path(path: str | None) -> str | None:
    """Return the allowlisted reader for a workspace path."""
    suffix = _suffix(path)
    return SOURCE_OPERATIONS.get(suffix) if suffix is not None else None


def destination_operation_for_path(path: str | None) -> str | None:
    """Return the allowlisted writer for a workspace path."""
    suffix = _suffix(path)
    return DESTINATION_OPERATIONS.get(suffix) if suffix is not None else None


def same_workspace_path(source: str | None, destination: str | None) -> bool:
    """Return whether two relative paths name the same workspace location."""
    if source is None or destination is None:
        return False
    return _normalized_path(source) == _normalized_path(destination)


def _normalized_path(value: str) -> str:
    normalized = value.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return PurePosixPath(normalized).as_posix().casefold()


__all__ = [
    "DESTINATION_OPERATIONS",
    "SOURCE_OPERATIONS",
    "SUPPORTED_DESTINATION_SUFFIXES",
    "SUPPORTED_SOURCE_SUFFIXES",
    "destination_operation_for_path",
    "same_workspace_path",
    "source_operation_for_path",
]
