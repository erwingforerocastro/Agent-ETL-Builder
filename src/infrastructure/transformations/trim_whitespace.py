"""Trim leading and trailing whitespace from text values."""

from collections.abc import Sequence
from typing import Literal

import pandas as pd

from application.registry.vocabulary import WHITESPACE_POLICIES
from domain.errors import TransformationError
from infrastructure.transformations._common import (
    is_text_column,
    require_columns,
    require_non_empty_columns,
    require_unique_columns,
)

TrimPolicy = Literal["both", "leading", "trailing"]

_POLICIES = frozenset(WHITESPACE_POLICIES)


def _trim_text_series(series: pd.Series, policy: TrimPolicy) -> pd.Series:
    if isinstance(series.dtype, pd.StringDtype):
        if policy == "leading":
            return series.str.lstrip()
        if policy == "trailing":
            return series.str.rstrip()
        return series.str.strip()

    def trim(value: object) -> object:
        if not isinstance(value, str):
            return value
        if policy == "leading":
            return value.lstrip()
        if policy == "trailing":
            return value.rstrip()
        return value.strip()

    return series.map(trim)


def trim_whitespace(
    df: pd.DataFrame,
    *,
    columns: Sequence[str] | None = None,
    policy: TrimPolicy = "both",
) -> pd.DataFrame:
    """Return a copy with text values trimmed according to policy."""
    require_unique_columns(df, module=__name__)
    require_non_empty_columns(columns, module=__name__, parameter="columns")
    if policy not in _POLICIES:
        raise TransformationError(
            code="TRANSFORMATION_INVALID_PARAMETER",
            message="Unsupported whitespace trim policy",
            module=__name__,
            context={"parameter": "policy"},
        )

    result = df.copy(deep=True)
    selected = None if columns is None else require_columns(df, columns, module=__name__)
    targets = list(result.columns) if selected is None else list(selected)

    for column in targets:
        series = result[column]
        if not is_text_column(series):
            if selected is not None:
                raise TransformationError(
                    code="TRANSFORMATION_UNSUPPORTED_DTYPE",
                    message="Whitespace trimming requires a text column",
                    module=__name__,
                    context={"column": str(column), "dtype": str(series.dtype)},
                )
            continue
        result[column] = _trim_text_series(series, policy)

    return result
