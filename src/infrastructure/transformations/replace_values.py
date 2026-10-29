"""Replace exact text values with another string or with null."""

from collections.abc import Sequence

import pandas as pd

from domain.errors import TransformationError
from infrastructure.transformations._common import (
    is_text_column,
    require_columns,
    require_non_empty_when_provided,
    require_unique_columns,
)


def _invalid_parameter(parameter: str) -> TransformationError:
    return TransformationError(
        code="TRANSFORMATION_INVALID_PARAMETER",
        message="Replacement parameter is invalid",
        module=__name__,
        context={"parameter": parameter},
    )


def _replace_error(*, column: str) -> TransformationError:
    return TransformationError(
        code="TRANSFORMATION_REPLACE_FAILED",
        message="Exact value replacement failed",
        module=__name__,
        context={"column": column},
    )


def replace_values(
    df: pd.DataFrame,
    *,
    columns: Sequence[str] | None = None,
    old: str,
    new: str | None = None,
) -> pd.DataFrame:
    """Return a copy with exact text matches replaced by ``new``."""
    require_unique_columns(df, module=__name__)
    require_non_empty_when_provided(columns, module=__name__, parameter="columns")
    if not isinstance(old, str):
        raise _invalid_parameter("old")
    if new is not None and not isinstance(new, str):
        raise _invalid_parameter("new")

    result = df.copy(deep=True)
    selected = None if columns is None else require_columns(df, columns, module=__name__)
    targets = list(result.columns) if selected is None else list(selected)

    for column in targets:
        series = result[column]
        if not is_text_column(series):
            if selected is not None:
                raise TransformationError(
                    code="TRANSFORMATION_UNSUPPORTED_DTYPE",
                    message="Exact replacement requires a text column",
                    module=__name__,
                    context={"column": str(column), "dtype": str(series.dtype)},
                )
            continue
        try:
            mask = (series.notna() & (series == old)).fillna(False).astype(bool)
            result[column] = series.mask(mask, new)
        except (TypeError, ValueError) as exc:
            raise _replace_error(column=str(column)) from exc

    return result


__all__ = ["replace_values"]
