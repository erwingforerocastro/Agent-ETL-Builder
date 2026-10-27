from typing import cast

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from domain.errors import TransformationError
from infrastructure.transformations.cast_column import (
    CastMode,
    TargetType,
    cast_column,
)


def test_cast_column_to_string_uses_nullable_strings() -> None:
    df = pd.DataFrame({"value": pd.Series([1, 2, None], dtype="Int64")})

    result = cast_column(df, column="value", target_type="string")

    assert result["value"].tolist()[:2] == ["1", "2"]
    assert pd.isna(result["value"].iloc[2])
    assert df["value"].iloc[0] == 1


def test_cast_column_to_integer_coerces_invalid_values() -> None:
    df = pd.DataFrame({"value": ["1", "2", None, ""]})

    result = cast_column(
        df,
        column="value",
        target_type="integer",
        errors="coerce",
    )

    assert result["value"].tolist()[:2] == [1, 2]
    assert pd.isna(result["value"].iloc[2])
    assert pd.isna(result["value"].iloc[3])


def test_cast_column_to_float_coerces_invalid_values() -> None:
    df = pd.DataFrame({"value": ["1.5", "bad"]})

    result = cast_column(
        df,
        column="value",
        target_type="float",
        errors="coerce",
    )

    assert result["value"].iloc[0] == 1.5
    assert pd.isna(result["value"].iloc[1])


def test_cast_column_reports_invalid_value_count() -> None:
    df = pd.DataFrame({"value": ["1", "bad", "also-bad"]})

    with pytest.raises(TransformationError) as caught:
        cast_column(df, column="value", target_type="integer")

    assert caught.value.code == "TRANSFORMATION_CAST_FAILED"
    assert caught.value.context == {
        "column": "value",
        "target_type": "integer",
        "invalid_count": 2,
    }


def test_cast_column_rejects_non_integral_values() -> None:
    df = pd.DataFrame({"value": [1.0, 2.5]})

    with pytest.raises(TransformationError) as invalid:
        cast_column(df, column="value", target_type="integer")
    result = cast_column(
        df,
        column="value",
        target_type="integer",
        errors="coerce",
    )

    assert invalid.value.code == "TRANSFORMATION_CAST_NON_INTEGRAL"
    assert invalid.value.context["invalid_count"] == 1
    assert result["value"].iloc[0] == 1
    assert pd.isna(result["value"].iloc[1])


def test_cast_column_handles_integer_overflow() -> None:
    df = pd.DataFrame({"value": [str(2**63)]})

    with pytest.raises(TransformationError) as invalid:
        cast_column(df, column="value", target_type="integer")
    result = cast_column(
        df,
        column="value",
        target_type="integer",
        errors="coerce",
    )

    assert invalid.value.code == "TRANSFORMATION_CAST_FAILED"
    assert invalid.value.context["invalid_count"] == 1
    assert pd.isna(result["value"].iloc[0])


def test_cast_column_is_idempotent() -> None:
    df = pd.DataFrame({"value": ["1", "2"]})

    once = cast_column(df, column="value", target_type="integer")
    twice = cast_column(once, column="value", target_type="integer")

    assert_frame_equal(once, twice)


def test_cast_column_rejects_missing_column() -> None:
    df = pd.DataFrame({"other": [1]})

    with pytest.raises(TransformationError) as caught:
        cast_column(df, column="value", target_type="integer")

    assert caught.value.code == "TRANSFORMATION_COLUMN_NOT_FOUND"


def test_cast_column_rejects_invalid_parameters() -> None:
    df = pd.DataFrame({"value": ["1"]})

    with pytest.raises(TransformationError) as target:
        cast_column(df, column="value", target_type=cast(TargetType, "date"))
    with pytest.raises(TransformationError) as mode:
        cast_column(
            df,
            column="value",
            target_type="integer",
            errors=cast(CastMode, "ignore"),
        )

    assert target.value.context == {"parameter": "target_type"}
    assert mode.value.context == {"parameter": "errors"}
