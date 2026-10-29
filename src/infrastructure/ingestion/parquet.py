"""Parquet ingestion with optional streaming row batches."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from domain.errors import IngestionError, SandboxError


def read_parquet(
    *,
    path: str = "input.parquet",
    columns: Sequence[str] | None = None,
) -> pd.DataFrame:
    selected = list(columns) if columns is not None else None
    try:
        with Path(path).open("rb") as handle:
            return pd.read_parquet(handle, columns=selected)
    except SandboxError:
        raise
    except Exception as exc:
        raise IngestionError(
            code="INGESTION_FAILED",
            message="Parquet ingestion failed",
            module=__name__,
            context={"path": path},
        ) from exc


def iter_parquet_chunks(
    *,
    path: str = "input.parquet",
    chunk_size: int = 10_000,
    columns: Sequence[str] | None = None,
) -> Iterator[pd.DataFrame]:
    """Yield Parquet row groups in batches without loading the whole file."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    selected = list(columns) if columns is not None else None
    try:
        with Path(path).open("rb") as handle:
            parquet_file = pq.ParquetFile(handle)
            for batch in parquet_file.iter_batches(
                batch_size=chunk_size,
                columns=selected,
            ):
                yield batch.to_pandas()
    except SandboxError:
        raise
    except Exception as exc:
        raise IngestionError(
            code="INGESTION_FAILED",
            message="Parquet ingestion failed",
            module=__name__,
            context={"path": path},
        ) from exc


__all__ = ["iter_parquet_chunks", "read_parquet"]
