"""Atomic Parquet loader."""

import pandas as pd

from domain.errors import LoadError, SandboxError
from infrastructure.loaders.atomic import atomic_binary


def save_parquet(df: pd.DataFrame, *, path: str = "output.parquet") -> pd.DataFrame:
    try:
        with atomic_binary(path) as handle:
            df.to_parquet(handle, index=False)
        return df.copy()
    except SandboxError:
        raise
    except Exception as exc:
        raise LoadError(
            code="LOAD_FAILED",
            message="Parquet load failed",
            module=__name__,
            context={"path": path},
        ) from exc


__all__ = ["save_parquet"]
