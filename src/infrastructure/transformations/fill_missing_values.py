"""Fill null values in one column with a constant or summary value."""

from typing import Any, Literal, cast

import pandas as pd

from application.registry.vocabulary import FILL_METHODS
from domain.errors import TransformationError
from infrastructure.transformations._common import (
    require_columns,
    require_unique_columns,
)

FillMethod = Literal["constant", "mean", "median", "mode"]

_METHODS = frozenset(FILL_METHODS)


def _invalid_parameter(parameter: str) -> TransformationError:
    return TransformationError(
        code="TRANSFORMATION_INVALID_PARAMETER",
        message="Imputation parameter is invalid",
        module=__name__,
        context={"parameter": parameter},
    )


def _imputation_error(
    *,
    column: str,
    method: FillMethod,
    message: str = "Column cannot be imputed",
) -> TransformationError:
    return TransformationError(
        code="TRANSFORMATION_IMPUTATION_FAILED",
        message=message,
        module=__name__,
        context={"column": column, "method": method},
    )


def _numeric_summary(series: pd.Series, method: FillMethod, column: str) -> float:
    if not pd.api.types.is_numeric_dtype(series.dtype):
        raise TransformationError(
            code="TRANSFORMATION_UNSUPPORTED_DTYPE",
            message="Mean and median imputation require a numeric column",
            module=__name__,
            context={"column": column, "dtype": str(series.dtype)},
        )
    present = series.dropna()
    if present.empty:
        raise _imputation_error(column=column, method=method)
    summary = present.mean() if method == "mean" else present.median()
    if pd.isna(summary):
        raise _imputation_error(column=column, method=method)
    return float(summary)


def _mode_summary(series: pd.Series, method: FillMethod, column: str) -> object:
    modes = series.dropna().mode(dropna=True)
    if modes.empty:
        raise _imputation_error(column=column, method=method)
    return modes.iloc[0]


def fill_missing_values(
    df: pd.DataFrame,
    *,
    column: str,
    method: FillMethod = "constant",
    value: str | int | float | None = None,
) -> pd.DataFrame:
    """Return a copy with nulls in one column filled by the selected method."""
    require_unique_columns(df, module=__name__)
    selected = require_columns(df, (column,), module=__name__)[0]
    if method not in _METHODS:
        raise _invalid_parameter("method")
    if method == "constant":
        if value is None:
            raise _invalid_parameter("value")
    elif value is not None:
        raise _invalid_parameter("value")

    result = df.copy(deep=True)
    series = result[selected]
    if not series.isna().any():
        return result

    try:
        if method == "constant":
            result[selected] = series.fillna(value)
        elif method in {"mean", "median"}:
            numeric_summary = _numeric_summary(series, method, str(selected))
            result[selected] = series.astype("Float64").fillna(numeric_summary)
        else:
            mode_summary = _mode_summary(series, method, str(selected))
            result[selected] = series.fillna(cast(Any, mode_summary))
    except TransformationError:
        raise
    except (OverflowError, TypeError, ValueError) as exc:
        raise _imputation_error(
            column=str(selected),
            method=method,
            message="Value could not be filled into the column",
        ) from exc
    return result


__all__ = ["FillMethod", "fill_missing_values"]
