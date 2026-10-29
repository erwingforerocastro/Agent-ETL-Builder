"""Filter rows with one declarative, literal predicate."""

from typing import Literal

import pandas as pd

from application.registry.vocabulary import FILTER_OPERATORS
from domain.errors import TransformationError
from infrastructure.transformations._common import (
    is_text_column,
    require_columns,
    require_unique_columns,
)

FilterOperator = Literal[
    "equals",
    "not_equals",
    "greater_than",
    "greater_or_equal",
    "less_than",
    "less_or_equal",
    "is_null",
    "is_not_null",
    "contains",
    "starts_with",
    "ends_with",
]

_OPERATORS = frozenset(FILTER_OPERATORS)
_NULL_OPERATORS = frozenset({"is_null", "is_not_null"})
_TEXT_OPERATORS = frozenset({"contains", "starts_with", "ends_with"})


def _invalid_parameter(parameter: str) -> TransformationError:
    return TransformationError(
        code="TRANSFORMATION_INVALID_PARAMETER",
        message="Filter parameter is invalid",
        module=__name__,
        context={"parameter": parameter},
    )


def _comparison_value(value: str | int | float | None) -> str | int | float:
    if value is None:
        raise _invalid_parameter("value")
    return value


def _text_value(value: str | int | float | None) -> str:
    if not isinstance(value, str):
        raise _invalid_parameter("value")
    return value


def _filter_error(*, column: str, operator: str) -> TransformationError:
    return TransformationError(
        code="TRANSFORMATION_FILTER_FAILED",
        message="Filter comparison failed",
        module=__name__,
        context={"column": column, "operator": operator},
    )


def _text_mask(series: pd.Series, operator: str, value: str) -> pd.Series:
    if operator == "contains":
        mask = series.str.contains(value, regex=False, na=False)
    elif operator == "starts_with":
        mask = series.str.startswith(value, na=False)
    else:
        mask = series.str.endswith(value, na=False)
    return series.notna() & mask.fillna(False)


def _comparison_mask(
    series: pd.Series,
    operator: str,
    value: str | int | float,
) -> pd.Series:
    if operator == "equals":
        comparison = series == value
    elif operator == "not_equals":
        comparison = series != value
    elif operator == "greater_than":
        comparison = series > value
    elif operator == "greater_or_equal":
        comparison = series >= value
    elif operator == "less_than":
        comparison = series < value
    else:
        comparison = series <= value
    return (series.notna() & comparison).fillna(False).astype(bool)


def filter_rows(
    df: pd.DataFrame,
    *,
    column: str,
    operator: FilterOperator,
    value: str | int | float | None = None,
) -> pd.DataFrame:
    """Return a copy with rows that match one literal predicate."""
    require_unique_columns(df, module=__name__)
    selected = require_columns(df, (column,), module=__name__)[0]
    if operator not in _OPERATORS:
        raise _invalid_parameter("operator")

    if operator in _NULL_OPERATORS:
        if value is not None:
            raise _invalid_parameter("value")
    else:
        if value is None:
            raise _invalid_parameter("value")
        if operator in _TEXT_OPERATORS and not isinstance(value, str):
            raise _invalid_parameter("value")

    series = df[selected]
    try:
        if operator == "is_null":
            mask = series.isna()
        elif operator == "is_not_null":
            mask = series.notna()
        elif operator in _TEXT_OPERATORS:
            if not is_text_column(series):
                raise TransformationError(
                    code="TRANSFORMATION_UNSUPPORTED_DTYPE",
                    message="Text matching requires a text column",
                    module=__name__,
                    context={"column": str(selected), "dtype": str(series.dtype)},
                )
            mask = _text_mask(series, operator, _text_value(value))
        else:
            mask = _comparison_mask(series, operator, _comparison_value(value))
    except TransformationError:
        raise
    except (TypeError, ValueError) as exc:
        raise _filter_error(column=str(selected), operator=operator) from exc

    return df.loc[mask].reset_index(drop=True)


__all__ = ["FilterOperator", "filter_rows"]
