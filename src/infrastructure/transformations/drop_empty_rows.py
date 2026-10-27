"""Drop rows whose selected values are all null or blank text."""

from collections.abc import Sequence

import pandas as pd

from infrastructure.transformations._common import (
    is_text_column,
    require_columns,
    require_non_empty_columns,
    require_unique_columns,
)


def _blank_mask(series: pd.Series) -> pd.Series:
    mask = series.isna()
    if is_text_column(series):
        blanks = series.map(lambda value: isinstance(value, str) and not value.strip())
        mask = mask | blanks.fillna(False).astype(bool)
    return mask


def drop_empty_rows(
    df: pd.DataFrame,
    *,
    subset: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Return a copy without rows that are empty across the selected columns."""
    require_unique_columns(df, module=__name__)
    require_non_empty_columns(subset, module=__name__, parameter="subset")

    if subset is None:
        masks = [_blank_mask(df.iloc[:, position]) for position in range(df.shape[1])]
    else:
        selected = require_columns(df, subset, module=__name__)
        masks = [_blank_mask(df[column]) for column in selected]

    if not masks:
        return df.copy(deep=True)

    all_blank = pd.concat(masks, axis=1).all(axis=1)
    return df.loc[~all_blank].reset_index(drop=True)
