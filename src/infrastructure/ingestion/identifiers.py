"""Stable source identifiers, hashes, and artifact names."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Final
from urllib.parse import parse_qsl, urlencode

import pandas as pd

from domain.entities.ingestion import SOURCE_TYPES, SourceIdentity, SourceType
from domain.errors import IngestionError, SandboxError

_HASH_PREFIX: Final[str] = "sha256:"
_UNSAFE_IDENTIFIER = re.compile(r"[^A-Za-z0-9_-]+")
_FILE_HASH_CHUNK_BYTES: Final[int] = 1024 * 1024
_SENSITIVE_QUERY_KEYS: Final[frozenset[str]] = frozenset(
    {"password", "passfile", "sslpassword", "user"}
)


def sanitize_identifier(value: str, *, max_length: int = 64) -> str:
    """Make a path-safe, length-limited identifier without path separators."""
    if max_length <= 0:
        raise ValueError("max_length must be positive")
    text = _UNSAFE_IDENTIFIER.sub("_", value.strip()).strip("_-") or "x"
    if len(text) > max_length:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
        text = f"{text[: max_length - 13]}_{digest}"
    return text


def credential_free_uri(uri: str) -> str:
    """Remove URI user information and sensitive query values before hashing."""
    text = uri.strip()
    if "://" not in text:
        return text
    scheme, rest = text.split("://", 1)
    if "@" in rest:
        rest = rest.rsplit("@", 1)[1]
    base, separator, query = rest.partition("?")
    if separator:
        pairs = parse_qsl(query, keep_blank_values=True)
        filtered = [
            (key, value) for key, value in pairs if key.lower() not in _SENSITIVE_QUERY_KEYS
        ]
        rest = base + (f"?{urlencode(filtered)}" if filtered else "")
    return f"{scheme.lower()}://{rest}"


def canonical_file_uri(path: str | Path) -> str:
    """Return a stable, credential-free identity for a workspace file."""
    try:
        resolved = Path(path).expanduser().resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise IngestionError(
            code="SOURCE_PATH_INVALID",
            message="Source path could not be resolved",
            module=__name__,
            context={"path": str(path)},
        ) from exc
    text = resolved.as_posix()
    if os.name == "nt":
        text = text.lower()
    return text


def source_id_for(source_type: SourceType, canonical_uri: str) -> str:
    """Return a stable source id derived from a canonical, credential-free URI."""
    if source_type not in SOURCE_TYPES:
        raise ValueError(f"unsupported source_type: {source_type}")
    text = credential_free_uri(canonical_uri)
    if not text:
        raise ValueError("canonical_uri must not be blank")
    digest = hashlib.sha256(f"{source_type}\0{text}".encode()).hexdigest()
    return f"src_{digest[:32]}"


def file_content_hash(path: str | Path) -> str:
    """Hash file bytes without loading the file into memory."""
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as handle:
            for block in iter(lambda: handle.read(_FILE_HASH_CHUNK_BYTES), b""):
                digest.update(block)
    except SandboxError:
        raise
    except OSError as exc:
        raise IngestionError(
            code="SOURCE_HASH_FAILED",
            message="Source content could not be read",
            module=__name__,
            context={"path": str(path)},
        ) from exc
    return f"{_HASH_PREFIX}{digest.hexdigest()}"


def frame_schema_hash(frame: pd.DataFrame) -> str:
    """Hash column order, names, and dtypes."""
    schema = [(str(name), str(dtype)) for name, dtype in frame.dtypes.items()]
    payload = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    return f"{_HASH_PREFIX}{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def frame_content_hash(frame: pd.DataFrame) -> str:
    """Hash schema plus row values, including the index."""
    digest = hashlib.sha256()
    digest.update(frame_schema_hash(frame).encode("utf-8"))
    try:
        row_hashes = pd.util.hash_pandas_object(frame, index=True, categorize=False)
    except (TypeError, ValueError):
        digest.update(_canonical_rows(frame).encode("utf-8"))
    else:
        digest.update(row_hashes.to_numpy().tobytes())
    return f"{_HASH_PREFIX}{digest.hexdigest()}"


def source_identity_for_frame(
    frame: pd.DataFrame,
    *,
    source_type: SourceType,
    canonical_uri: str,
    content_hash: str | None = None,
) -> SourceIdentity:
    """Build a source identity for an already-read DataFrame."""
    return SourceIdentity(
        source_id=source_id_for(source_type, canonical_uri),
        source_type=source_type,
        content_hash=content_hash or frame_content_hash(frame),
        schema_hash=frame_schema_hash(frame),
        row_count=len(frame),
    )


def source_identity_for_file(
    path: str | Path,
    frame: pd.DataFrame,
    *,
    source_type: SourceType,
) -> SourceIdentity:
    """Build a source identity using file bytes for the content hash."""
    return source_identity_for_frame(
        frame,
        source_type=source_type,
        canonical_uri=canonical_file_uri(path),
        content_hash=file_content_hash(path),
    )


def artifact_id(
    run_id: str,
    source_id: str,
    artifact_type: str,
    chunk_index: int | None = None,
) -> str:
    """Build a sanitized artifact name from run, source, type, and chunk index."""
    parts = [
        sanitize_identifier(run_id, max_length=64),
        sanitize_identifier(source_id, max_length=64),
        sanitize_identifier(artifact_type, max_length=32),
    ]
    if chunk_index is not None:
        if not isinstance(chunk_index, int) or isinstance(chunk_index, bool) or chunk_index < 0:
            raise ValueError("chunk_index must be a non-negative integer")
        parts.append(f"{chunk_index:06d}")
    identifier = "_".join(parts)
    return identifier


def _canonical_rows(frame: pd.DataFrame) -> str:
    records: list[dict[str, str]] = []
    for index, row in frame.iterrows():
        record = {"index": _canonical_cell(index)}
        record.update({str(column): _canonical_cell(row[column]) for column in frame.columns})
        records.append(record)
    return json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _canonical_cell(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, float):
        if math.isnan(value):
            return "nan"
        if math.isinf(value):
            return "inf" if value > 0 else "-inf"
        return repr(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, Mapping):
        return json.dumps(
            {str(key): _canonical_cell(item) for key, item in value.items()},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    if isinstance(value, list | tuple):
        return json.dumps(
            [_canonical_cell(item) for item in value],
            ensure_ascii=False,
            separators=(",", ":"),
        )
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return json.dumps(isoformat(), ensure_ascii=False)
    return json.dumps(repr(value), ensure_ascii=False)


__all__ = [
    "artifact_id",
    "canonical_file_uri",
    "credential_free_uri",
    "file_content_hash",
    "frame_content_hash",
    "frame_schema_hash",
    "sanitize_identifier",
    "source_id_for",
    "source_identity_for_file",
    "source_identity_for_frame",
]
