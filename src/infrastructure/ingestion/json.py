"""JSON and JSONL ingestion with optional streaming chunks."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Literal

import pandas as pd

from domain.errors import IngestionError, SandboxError
from infrastructure.ingestion.chunking import iter_frame_chunks

JsonOrient = Literal["split", "records", "index", "columns", "values", "table"]


def read_json(
    *,
    path: str = "input.json",
    encoding: str = "utf-8-sig",
    orient: JsonOrient | None = None,
) -> pd.DataFrame:
    if _is_empty_file(path):
        return pd.DataFrame()
    try:
        return pd.read_json(path, encoding=encoding, orient=orient)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()
    except SandboxError:
        raise
    except Exception as exc:
        raise IngestionError(
            code="INGESTION_FAILED",
            message="JSON ingestion failed",
            module=__name__,
            context={"path": path},
        ) from exc


def read_jsonl(
    *,
    path: str = "input.jsonl",
    encoding: str = "utf-8-sig",
) -> pd.DataFrame:
    if _is_empty_file(path):
        return pd.DataFrame()
    try:
        return pd.read_json(path, encoding=encoding, lines=True)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()
    except SandboxError:
        raise
    except Exception as exc:
        raise IngestionError(
            code="INGESTION_FAILED",
            message="JSONL ingestion failed",
            module=__name__,
            context={"path": path},
        ) from exc


def iter_json_chunks(
    *,
    path: str = "input.json",
    chunk_size: int = 10_000,
    encoding: str = "utf-8-sig",
    orient: JsonOrient | None = None,
) -> Iterator[pd.DataFrame]:
    """Yield chunks from a JSON array; the document is parsed before chunking."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    frame = read_json(path=path, encoding=encoding, orient=orient)
    for _, chunk in iter_frame_chunks(frame, chunk_size):
        yield chunk


def iter_jsonl_chunks(
    *,
    path: str = "input.jsonl",
    chunk_size: int = 10_000,
    encoding: str = "utf-8-sig",
) -> Iterator[pd.DataFrame]:
    """Yield JSONL rows in order without loading the whole file."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    try:
        reader = pd.read_json(
            path,
            encoding=encoding,
            lines=True,
            chunksize=chunk_size,
        )
        for chunk in reader:
            yield chunk.copy()
    except pd.errors.EmptyDataError:
        return
    except SandboxError:
        raise
    except Exception as exc:
        raise IngestionError(
            code="INGESTION_FAILED",
            message="JSONL ingestion failed",
            module=__name__,
            context={"path": path},
        ) from exc


def _is_empty_file(path: str) -> bool:
    try:
        with Path(path).open("rb") as handle:
            return not handle.read(1)
    except SandboxError:
        raise
    except OSError:
        return False


__all__ = ["iter_json_chunks", "iter_jsonl_chunks", "read_json", "read_jsonl"]
