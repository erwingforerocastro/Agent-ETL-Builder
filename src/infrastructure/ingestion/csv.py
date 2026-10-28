"""CSV ingestion."""

import pandas as pd

from domain.errors import IngestionError, SandboxError


def read_csv(*, path: str = "input.csv", df: pd.DataFrame | None = None) -> pd.DataFrame:
    try:
        if df is not None:
            return df.copy()
        return pd.read_csv(path)
    except SandboxError:
        raise
    except Exception as exc:
        raise IngestionError(
            code="INGESTION_FAILED",
            message="CSV ingestion failed",
            module=__name__,
            context={"path": path},
        ) from exc
