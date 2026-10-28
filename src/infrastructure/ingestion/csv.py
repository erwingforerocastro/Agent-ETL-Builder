"""CSV ingestion."""

import pandas as pd

from domain.errors import TransformationError


def read_csv(*, path: str = "input.csv", df: pd.DataFrame | None = None) -> pd.DataFrame:
    try:
        if df is not None:
            return df.copy()
        return pd.read_csv(path)
    except Exception as exc:
        raise TransformationError(
            code="INGESTION_FAILED",
            message=str(exc),
            module=__name__,
        ) from exc
