"""Parse a date column and format it with a strftime pattern."""

from typing import Literal

import pandas as pd

from application.registry.vocabulary import DATE_PARSE_MODES
from domain.errors import TransformationError
from infrastructure.transformations._common import (
    is_text_column,
    require_columns,
    require_unique_columns,
)

DateParseMode = Literal["raise", "coerce"]

_ERROR_MODES = frozenset(DATE_PARSE_MODES)


def _invalid_parameter(parameter: str) -> TransformationError:
    return TransformationError(
        code="TRANSFORMATION_INVALID_PARAMETER",
        message="Date normalization parameter is invalid",
        module=__name__,
        context={"parameter": parameter},
    )


def _date_parse_error(
    *,
    column: str,
    invalid_count: int | None = None,
    message: str = "Column contains values that cannot be parsed as dates",
) -> TransformationError:
    context: dict[str, object] = {"column": column}
    if invalid_count is not None:
        context["invalid_count"] = invalid_count
    return TransformationError(
        code="TRANSFORMATION_DATE_PARSE_FAILED",
        message=message,
        module=__name__,
        context=context,
    )


def normalize_dates(
    df: pd.DataFrame,
    *,
    column: str,
    output_format: str,
    errors: DateParseMode = "raise",
) -> pd.DataFrame:
    """Return a copy with one date column parsed and formatted as text."""
    require_unique_columns(df, module=__name__)
    selected = require_columns(df, (column,), module=__name__)[0]
    if not isinstance(output_format, str) or not output_format.strip():
        raise _invalid_parameter("output_format")
    if errors not in _ERROR_MODES:
        raise _invalid_parameter("errors")

    result = df.copy(deep=True)
    series = result[selected]
    try:
        if pd.api.types.is_datetime64_any_dtype(series.dtype):
            parsed = series
        elif is_text_column(series):
            parsed = pd.to_datetime(series, errors="coerce", format="mixed")
            invalid = series.notna() & parsed.isna()
            if errors == "raise" and bool(invalid.any()):
                raise _date_parse_error(
                    column=str(selected),
                    invalid_count=int(invalid.sum()),
                )
        else:
            raise TransformationError(
                code="TRANSFORMATION_UNSUPPORTED_DTYPE",
                message="Date normalization requires a text or datetime column",
                module=__name__,
                context={"column": str(selected), "dtype": str(series.dtype)},
            )

        if not pd.api.types.is_datetime64_any_dtype(parsed.dtype):
            raise _date_parse_error(
                column=str(selected),
                message="Date parsing produced a non-datetime result",
            )
        formatted = parsed.dt.strftime(output_format)
    except TransformationError:
        raise
    except (OverflowError, TypeError, ValueError) as exc:
        raise _date_parse_error(column=str(selected)) from exc

    result[selected] = formatted.astype("string")
    return result


__all__ = ["DateParseMode", "normalize_dates"]
