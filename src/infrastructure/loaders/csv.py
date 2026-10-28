"""CSV loaders."""

import pandas as pd

from domain.errors import TransformationError


def save_csv(df: pd.DataFrame, *, path: str = "output.csv") -> pd.DataFrame:
    try:
        df.to_csv(path, index=False)
        return df.copy()
    except Exception as exc:
        raise TransformationError(
            code="LOAD_FAILED",
            message=str(exc),
            module=__name__,
        ) from exc
