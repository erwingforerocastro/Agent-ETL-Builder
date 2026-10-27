"""Cast one column to a supported scalar type."""

from typing import Literal

import pandas as pd

from domain.errors import TransformationError
from infrastructure.transformations._common import (
    require_columns,
    require_unique_columns,
)

TargetType = Literal["string", "integer", "float"]
CastMode = Literal["raise", "coerce"]

_TARGET_TYPES = frozenset({"string", "integer", "float"})
_CAST_MODES = frozenset({"raise", "coerce"})
_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1


def _cast_error(
    *,
    code: str,
    message: str,
    column: str,
    target_type: TargetType,
    invalid_count: int | None = None,
) -> TransformationError:
    context: dict[str, object] = {"column": column, "target_type": target_type}
    if invalid_count is not None:
        context["invalid_count"] = invalid_count
    return TransformationError(
        code=code,
        message=message,
        module=__name__,
        context=context,
    )


def cast_column(
    df: pd.DataFrame,
    *,
    column: str,
    target_type: TargetType,
    errors: CastMode = "raise",
) -> pd.DataFrame:
    """Return a copy with one column cast to string, integer, or float."""
    require_unique_columns(df, module=__name__)
    require_columns(df, (column,), module=__name__)
    if target_type not in _TARGET_TYPES:
        raise TransformationError(
            code="TRANSFORMATION_INVALID_PARAMETER",
            message="Unsupported cast target type",
            module=__name__,
            context={"parameter": "target_type"},
        )
    if errors not in _CAST_MODES:
        raise TransformationError(
            code="TRANSFORMATION_INVALID_PARAMETER",
            message="Unsupported cast error mode",
            module=__name__,
            context={"parameter": "errors"},
        )

    result = df.copy(deep=True)
    series = result[column]

    try:
        if target_type == "string":
            result[column] = series.astype("string")
            return result

        numeric = pd.to_numeric(series, errors="coerce")
        invalid = series.notna() & numeric.isna()
        if errors == "raise" and bool(invalid.any()):
            raise _cast_error(
                code="TRANSFORMATION_CAST_FAILED",
                message="Column contains values that cannot be cast",
                column=column,
                target_type=target_type,
                invalid_count=int(invalid.sum()),
            )

        if target_type == "integer":
            non_integral = numeric.notna() & (numeric % 1 != 0)
            out_of_bounds = numeric.notna() & ((numeric < _INT64_MIN) | (numeric > _INT64_MAX))
            if errors == "raise" and bool(non_integral.any()):
                raise _cast_error(
                    code="TRANSFORMATION_CAST_NON_INTEGRAL",
                    message="Integer cast requires whole numbers",
                    column=column,
                    target_type=target_type,
                    invalid_count=int(non_integral.sum()),
                )
            if errors == "raise" and bool(out_of_bounds.any()):
                raise _cast_error(
                    code="TRANSFORMATION_CAST_FAILED",
                    message="Column contains integers outside the 64-bit range",
                    column=column,
                    target_type=target_type,
                    invalid_count=int(out_of_bounds.sum()),
                )
            numeric = numeric.mask(non_integral | out_of_bounds)
            result[column] = numeric.astype("Int64")
        else:
            result[column] = numeric.astype("Float64")
        return result
    except TransformationError:
        raise
    except (OverflowError, TypeError, ValueError) as exc:
        raise _cast_error(
            code="TRANSFORMATION_CAST_FAILED",
            message="Column cast failed",
            column=column,
            target_type=target_type,
        ) from exc
