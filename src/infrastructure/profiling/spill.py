"""Temporary Parquet spill storage for exact numeric profiles."""

from __future__ import annotations

import contextlib
import hashlib
import os
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Protocol
from uuid import uuid4

import pandas as pd
import pyarrow.parquet as pq

from application.profiling.models import ProfileRequest
from domain.errors import ProfilingError, SandboxError
from infrastructure.ingestion.identifiers import artifact_id, sanitize_identifier
from infrastructure.profiling.paths import safe_component

_SPILL_BATCH_SIZE = 4_096


class NumericSpillPort(Protocol):
    """Write sorted numeric values and stream them back for an exact merge."""

    def write(
        self,
        request: ProfileRequest,
        *,
        chunk_index: int,
        column: str,
        values: Sequence[float],
    ) -> str: ...

    def iter_values(self, ref: str) -> Iterator[float]: ...


class FilesystemNumericSpillStore:
    """Stores sorted per-chunk numeric values in temporary Parquet files."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def write(
        self,
        request: ProfileRequest,
        *,
        chunk_index: int,
        column: str,
        values: Sequence[float],
    ) -> str:
        if not values:
            raise ValueError("numeric spill values must not be empty")
        digest = hashlib.sha256(column.encode()).hexdigest()[:12]
        column_id = sanitize_identifier(column, max_length=48)
        run_id = safe_component(request.run_id, "run_id")
        source_id = safe_component(request.source_id, "source_id")
        source_type = safe_component(request.source_type, "source_type")
        artifact_type = f"{source_type}_numeric_{column_id}_{digest}"
        identifier = artifact_id(
            run_id,
            source_id,
            artifact_type,
            chunk_index,
        )
        path = self._root / run_id / f"{identifier}.parquet"
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame({"value": sorted(values)}).to_parquet(temporary, index=False)
            os.replace(temporary, path)
        except SandboxError:
            raise
        except Exception as exc:
            with contextlib.suppress(OSError):
                temporary.unlink(missing_ok=True)
            raise ProfilingError(
                code="PROFILE_SPILL_WRITE_FAILED",
                message="Numeric spill artifact could not be written",
                module=__name__,
                context={
                    "chunk_index": chunk_index,
                    "column": column,
                    "error_type": type(exc).__name__,
                },
            ) from exc
        return path.relative_to(self._root).as_posix()

    def iter_values(self, ref: str) -> Iterator[float]:
        path = self._resolve(ref)
        try:
            with path.open("rb") as handle:
                parquet_file = pq.ParquetFile(handle)
                for batch in parquet_file.iter_batches(
                    batch_size=_SPILL_BATCH_SIZE,
                    columns=["value"],
                ):
                    for value in batch.column(0).to_pylist():
                        yield float(value)
        except SandboxError:
            raise
        except Exception as exc:
            raise ProfilingError(
                code="PROFILE_SPILL_READ_FAILED",
                message="Numeric spill artifact could not be read",
                module=__name__,
                context={"ref": ref, "error_type": type(exc).__name__},
            ) from exc

    def _resolve(self, ref: str) -> Path:
        try:
            path = (self._root / ref).resolve()
            path.relative_to(self._root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ProfilingError(
                code="PROFILE_SPILL_REF_INVALID",
                message="Numeric spill reference is outside the spill root",
                module=__name__,
                context={"ref": ref},
            ) from exc
        return path


__all__ = ["FilesystemNumericSpillStore", "NumericSpillPort"]
