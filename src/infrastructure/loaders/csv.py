"""Atomic CSV loader."""

import pandas as pd

from domain.errors import LoadError, SandboxError
from infrastructure.loaders.atomic import atomic_text


def save_csv(df: pd.DataFrame, *, path: str = "output.csv") -> pd.DataFrame:
    try:
        with atomic_text(path, newline="") as handle:
            df.to_csv(handle, index=False)
        return df.copy()
    except SandboxError:
        raise
    except Exception as exc:
        raise LoadError(
            code="LOAD_FAILED",
            message="CSV load failed",
            module=__name__,
            context={"path": path},
        ) from exc


__all__ = ["save_csv"]
