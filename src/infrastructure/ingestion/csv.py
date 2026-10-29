"""CSV ingestion with optional streaming chunks."""

from collections.abc import Iterator

import pandas as pd

from domain.errors import IngestionError, SandboxError


def read_csv(
    *,
    path: str = "input.csv",
    encoding: str = "utf-8-sig",
    delimiter: str = ",",
    quotechar: str = '"',
    df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if df is not None:
        return df.copy()
    try:
        return pd.read_csv(
            path,
            encoding=encoding,
            delimiter=delimiter,
            quotechar=quotechar,
        )
    except pd.errors.EmptyDataError:
        return pd.DataFrame()
    except SandboxError:
        raise
    except Exception as exc:
        raise IngestionError(
            code="INGESTION_FAILED",
            message="CSV ingestion failed",
            module=__name__,
            context={"path": path},
        ) from exc


def iter_csv_chunks(
    *,
    path: str = "input.csv",
    chunk_size: int = 10_000,
    encoding: str = "utf-8-sig",
    delimiter: str = ",",
    quotechar: str = '"',
) -> Iterator[pd.DataFrame]:
    """Yield CSV rows in order without loading the whole file."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    try:
        reader = pd.read_csv(
            path,
            encoding=encoding,
            delimiter=delimiter,
            quotechar=quotechar,
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
            message="CSV ingestion failed",
            module=__name__,
            context={"path": path},
        ) from exc


__all__ = ["iter_csv_chunks", "read_csv"]
