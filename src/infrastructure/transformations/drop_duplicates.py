"""Drop duplicate rows with an explicit retention policy."""

from collections.abc import Sequence
from typing import Literal

import pandas as pd

from infrastructure.transformations._common import (
    require_columns,
    require_non_empty_columns,
    require_unique_columns,
)

KeepPolicy = Literal["first", "last"]


def drop_duplicate_rows(
    df: pd.DataFrame,
    *,
    subset: Sequence[str] | None = None,
    keep: KeepPolicy = "first",
) -> pd.DataFrame:
    """Return a copy with duplicate rows removed and a reset index."""
    require_unique_columns(df, module=__name__)
    require_non_empty_columns(subset, module=__name__, parameter="subset")
    selected = None if subset is None else require_columns(df, subset, module=__name__)
    return df.drop_duplicates(subset=selected, keep=keep).reset_index(drop=True)
