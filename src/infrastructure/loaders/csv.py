"""CSV loaders."""

import pandas as pd

from domain.errors import LoadError, SandboxError


def save_csv(df: pd.DataFrame, *, path: str = "output.csv") -> pd.DataFrame:
    try:
        df.to_csv(path, index=False)
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
