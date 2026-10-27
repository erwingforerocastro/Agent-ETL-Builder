"""Validation helpers shared by transformation modules."""

from collections.abc import Sequence

import pandas as pd

from domain.errors import TransformationError


def require_unique_columns(df: pd.DataFrame, *, module: str) -> None:
    duplicates = [str(column) for column in df.columns[df.columns.duplicated()].tolist()]
    if duplicates:
        raise TransformationError(
            code="TRANSFORMATION_DUPLICATE_COLUMN_NAME",
            message="DataFrame contains duplicate column names",
            module=module,
            context={"duplicate_columns": duplicates},
        )


def require_columns(df: pd.DataFrame, columns: Sequence[str], *, module: str) -> tuple[str, ...]:
    resolved = tuple(dict.fromkeys(columns))
    missing = [column for column in resolved if column not in df.columns]
    if missing:
        raise TransformationError(
            code="TRANSFORMATION_COLUMN_NOT_FOUND",
            message="One or more required columns are missing",
            module=module,
            context={"missing_columns": missing},
        )
    return resolved


def require_non_empty_columns(
    columns: Sequence[str] | None,
    *,
    module: str,
    parameter: str,
) -> None:
    if columns is not None and not columns:
        raise TransformationError(
            code="TRANSFORMATION_INVALID_PARAMETER",
            message=f"{parameter} must not be empty",
            module=module,
            context={"parameter": parameter},
        )


def is_text_column(series: pd.Series) -> bool:
    return isinstance(series.dtype, pd.StringDtype) or pd.api.types.is_object_dtype(series)
