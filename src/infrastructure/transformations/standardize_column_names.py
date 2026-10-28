"""Normalize DataFrame column names to a stable snake_case form."""

import re
import unicodedata
from typing import Literal

import pandas as pd

from application.registry.vocabulary import COLUMN_CASES
from domain.errors import TransformationError
from infrastructure.transformations._common import require_unique_columns

ColumnCase = Literal["lower", "upper", "preserve"]

_CASES = frozenset(COLUMN_CASES)


def _normalize_name(name: str, case: ColumnCase) -> str:
    normalized = unicodedata.normalize("NFKC", name).strip()
    normalized = re.sub(r"\W+", "_", normalized, flags=re.UNICODE)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    if case == "upper":
        return normalized.upper()
    if case == "preserve":
        return normalized
    return normalized.lower()


def standardize_column_names(
    df: pd.DataFrame,
    *,
    case: ColumnCase = "lower",
) -> pd.DataFrame:
    """Return a copy with normalized, collision-free column names."""
    require_unique_columns(df, module=__name__)
    if case not in _CASES:
        raise TransformationError(
            code="TRANSFORMATION_INVALID_PARAMETER",
            message="Unsupported column name case policy",
            module=__name__,
            context={"parameter": "case"},
        )
    if isinstance(df.columns, pd.MultiIndex):
        raise TransformationError(
            code="TRANSFORMATION_UNSUPPORTED_DTYPE",
            message="MultiIndex columns are not supported",
            module=__name__,
        )

    normalized = [_normalize_name(str(column), case) for column in df.columns]
    seen: dict[str, int] = {}
    for index, name in enumerate(normalized):
        if not name:
            raise TransformationError(
                code="TRANSFORMATION_INVALID_COLUMN_NAME",
                message="Column normalization produced a blank name",
                module=__name__,
                context={"column_index": index},
            )
        if name in seen:
            raise TransformationError(
                code="TRANSFORMATION_DUPLICATE_COLUMN_NAME",
                message="Column normalization produced duplicate names",
                module=__name__,
                context={
                    "normalized_name": name,
                    "column_indices": [seen[name], index],
                },
            )
        seen[name] = index

    result = df.copy(deep=True)
    result.columns = normalized
    return result
