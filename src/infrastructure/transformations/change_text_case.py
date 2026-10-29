"""Change the case of text values in selected or all text columns."""

from collections.abc import Sequence
from typing import Literal

import pandas as pd

from application.registry.vocabulary import TEXT_CASES
from domain.errors import TransformationError
from infrastructure.transformations._common import (
    is_text_column,
    require_columns,
    require_non_empty_when_provided,
    require_unique_columns,
)

TextCase = Literal["lower", "upper", "title"]

_CASES = frozenset(TEXT_CASES)


def _change_value(value: str, case: TextCase) -> str:
    if case == "upper":
        return value.upper()
    if case == "title":
        return value.title()
    return value.lower()


def _change_series(series: pd.Series, case: TextCase) -> pd.Series:
    if isinstance(series.dtype, pd.StringDtype):
        if case == "upper":
            return series.str.upper()
        if case == "title":
            return series.str.title()
        return series.str.lower()

    def convert(value: object) -> object:
        if not isinstance(value, str):
            return value
        return _change_value(value, case)

    return series.map(convert)


def change_text_case(
    df: pd.DataFrame,
    *,
    columns: Sequence[str] | None = None,
    case: TextCase = "lower",
) -> pd.DataFrame:
    """Return a copy with text values changed to the selected case."""
    require_unique_columns(df, module=__name__)
    require_non_empty_when_provided(columns, module=__name__, parameter="columns")
    if case not in _CASES:
        raise TransformationError(
            code="TRANSFORMATION_INVALID_PARAMETER",
            message="Unsupported text case policy",
            module=__name__,
            context={"parameter": "case"},
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
                    message="Text case changes require a text column",
                    module=__name__,
                    context={"column": str(column), "dtype": str(series.dtype)},
                )
            continue
        result[column] = _change_series(series, case)

    return result


__all__ = ["TextCase", "change_text_case"]
