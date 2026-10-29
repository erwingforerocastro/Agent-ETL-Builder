from typing import cast

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from domain.errors import TransformationError
from infrastructure.transformations.fill_missing_values import (
    FillMethod,
    fill_missing_values,
)


def test_fill_missing_values_uses_a_constant_and_keeps_blank_text() -> None:
    df = pd.DataFrame({"name": ["Ada", None, ""]})

    result = fill_missing_values(
        df,
        column="name",
        method="constant",
        value="unknown",
    )

    assert result["name"].tolist() == ["Ada", "unknown", ""]
    assert pd.isna(df["name"].iloc[1])


def test_fill_missing_values_preserves_nullable_integer_dtype_for_constants() -> None:
    df = pd.DataFrame({"amount": pd.Series([1, None, 3], dtype="Int64")})

    result = fill_missing_values(
        df,
        column="amount",
        method="constant",
        value=0,
    )

    assert result["amount"].tolist() == [1, 0, 3]
    assert str(result["amount"].dtype) == "Int64"


def test_fill_missing_values_supports_mean_and_median() -> None:
    df = pd.DataFrame({"amount": [1.0, None, 3.0]})

    mean = fill_missing_values(df, column="amount", method="mean")
    median = fill_missing_values(df, column="amount", method="median")

    assert mean["amount"].tolist() == [1.0, 2.0, 3.0]
    assert median["amount"].tolist() == [1.0, 2.0, 3.0]


def test_fill_missing_values_uses_a_deterministic_mode_tie_break() -> None:
    df = pd.DataFrame({"status": ["b", "a", None, "b", "a"]})

    result = fill_missing_values(df, column="status", method="mode")

    assert result["status"].tolist() == ["b", "a", "a", "b", "a"]


def test_fill_missing_values_rejects_all_null_columns() -> None:
    df = pd.DataFrame({"amount": pd.Series([None, None], dtype="Float64")})

    with pytest.raises(TransformationError) as caught:
        fill_missing_values(df, column="amount", method="mean")

    assert caught.value.code == "TRANSFORMATION_IMPUTATION_FAILED"
    assert caught.value.context == {"column": "amount", "method": "mean"}


def test_fill_missing_values_rejects_non_numeric_mean_and_median() -> None:
    df = pd.DataFrame({"name": ["Ada", None]})

    with pytest.raises(TransformationError) as caught:
        fill_missing_values(df, column="name", method="median")

    assert caught.value.code == "TRANSFORMATION_UNSUPPORTED_DTYPE"
    assert caught.value.context["column"] == "name"
    assert caught.value.context["dtype"] == "str"


def test_fill_missing_values_rejects_all_null_mode() -> None:
    df = pd.DataFrame({"status": pd.Series([None, None], dtype="string")})

    with pytest.raises(TransformationError) as caught:
        fill_missing_values(df, column="status", method="mode")

    assert caught.value.code == "TRANSFORMATION_IMPUTATION_FAILED"
    assert caught.value.context == {"column": "status", "method": "mode"}


def test_fill_missing_values_wraps_incompatible_constant_values() -> None:
    df = pd.DataFrame({"amount": pd.Series([1, None], dtype="Int64")})

    with pytest.raises(TransformationError) as caught:
        fill_missing_values(df, column="amount", method="constant", value="x")

    assert caught.value.code == "TRANSFORMATION_IMPUTATION_FAILED"
    assert caught.value.context == {"column": "amount", "method": "constant"}


def test_fill_missing_values_rejects_invalid_parameter_combinations() -> None:
    df = pd.DataFrame({"value": [1, None]})

    with pytest.raises(TransformationError) as method:
        fill_missing_values(df, column="value", method=cast(FillMethod, "interpolate"))
    with pytest.raises(TransformationError) as constant:
        fill_missing_values(df, column="value", method="constant")
    with pytest.raises(TransformationError) as summary:
        fill_missing_values(df, column="value", method="mean", value=1)

    assert method.value.context == {"parameter": "method"}
    assert constant.value.context == {"parameter": "value"}
    assert summary.value.context == {"parameter": "value"}


def test_fill_missing_values_rejects_missing_column() -> None:
    df = pd.DataFrame({"value": [1, None]})

    with pytest.raises(TransformationError) as caught:
        fill_missing_values(df, column="missing", method="constant", value=0)

    assert caught.value.code == "TRANSFORMATION_COLUMN_NOT_FOUND"


def test_fill_missing_values_returns_a_copy_when_nothing_is_missing() -> None:
    df = pd.DataFrame({"value": [1, 2]})

    result = fill_missing_values(df, column="value", method="mean")

    assert_frame_equal(result, df)
    assert result is not df


def test_fill_missing_values_is_idempotent() -> None:
    df = pd.DataFrame({"amount": [1.0, None, 3.0]})

    once = fill_missing_values(df, column="amount", method="mean")
    twice = fill_missing_values(once, column="amount", method="mean")

    assert_frame_equal(once, twice)
