from typing import cast

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from domain.errors import TransformationError
from infrastructure.transformations.filter_rows import FilterOperator, filter_rows


def test_filter_rows_supports_equals_and_resets_index() -> None:
    df = pd.DataFrame(
        {
            "status": ["active", "inactive", "active"],
            "value": [1, 2, 3],
        }
    )

    result = filter_rows(df, column="status", operator="equals", value="active")

    assert result["value"].tolist() == [1, 3]
    assert result.index.tolist() == [0, 1]
    assert df["status"].tolist() == ["active", "inactive", "active"]


@pytest.mark.parametrize(
    ("operator", "expected"),
    [
        ("greater_than", [3, 4]),
        ("greater_or_equal", [2, 3, 4]),
        ("less_than", [1]),
        ("less_or_equal", [1, 2]),
        ("not_equals", [1, 3, 4]),
    ],
)
def test_filter_rows_supports_numeric_comparisons(
    operator: FilterOperator,
    expected: list[int],
) -> None:
    df = pd.DataFrame({"value": [1, 2, 3, 4]})

    result = filter_rows(df, column="value", operator=operator, value=2)

    assert result["value"].tolist() == expected


def test_filter_rows_supports_null_operators() -> None:
    df = pd.DataFrame({"value": [1, None, 3]})

    nulls = filter_rows(df, column="value", operator="is_null")
    present = filter_rows(df, column="value", operator="is_not_null")

    assert nulls["value"].isna().all()
    assert len(nulls) == 1
    assert present["value"].tolist() == [1, 3]


def test_filter_rows_text_operators_are_literal_and_case_sensitive() -> None:
    df = pd.DataFrame({"text": ["a.*", "abc", "Ada", "ada"]})

    contains = filter_rows(df, column="text", operator="contains", value="a.*")
    starts = filter_rows(df, column="text", operator="starts_with", value="A")
    ends = filter_rows(df, column="text", operator="ends_with", value="a")

    assert contains["text"].tolist() == ["a.*"]
    assert starts["text"].tolist() == ["Ada"]
    assert ends["text"].tolist() == ["Ada", "ada"]


def test_filter_rows_does_not_match_nulls_for_comparisons() -> None:
    df = pd.DataFrame({"value": ["x", None, "y"]})

    result = filter_rows(df, column="value", operator="not_equals", value="x")

    assert result["value"].tolist() == ["y"]


def test_filter_rows_equality_does_not_evaluate_other_comparisons() -> None:
    df = pd.DataFrame({"mixed": pd.Series(["x", 5, None], dtype=object)})

    result = filter_rows(df, column="mixed", operator="equals", value="x")

    assert result["mixed"].tolist() == ["x"]


def test_filter_rows_rejects_missing_column() -> None:
    df = pd.DataFrame({"value": [1]})

    with pytest.raises(TransformationError) as caught:
        filter_rows(df, column="missing", operator="equals", value=1)

    assert caught.value.code == "TRANSFORMATION_COLUMN_NOT_FOUND"


def test_filter_rows_rejects_invalid_operator_and_value_shapes() -> None:
    df = pd.DataFrame({"value": [1]})

    with pytest.raises(TransformationError) as operator:
        filter_rows(df, column="value", operator=cast(FilterOperator, "regex"), value=1)
    with pytest.raises(TransformationError) as missing_value:
        filter_rows(df, column="value", operator="equals")
    with pytest.raises(TransformationError) as null_value:
        filter_rows(df, column="value", operator="is_null", value=1)
    with pytest.raises(TransformationError) as text_value:
        filter_rows(df, column="value", operator="contains", value=1)

    assert operator.value.context == {"parameter": "operator"}
    assert missing_value.value.context == {"parameter": "value"}
    assert null_value.value.context == {"parameter": "value"}
    assert text_value.value.context == {"parameter": "value"}


def test_filter_rows_rejects_text_operators_on_non_text_columns() -> None:
    df = pd.DataFrame({"value": [1, 2]})

    with pytest.raises(TransformationError) as caught:
        filter_rows(df, column="value", operator="contains", value="1")

    assert caught.value.code == "TRANSFORMATION_UNSUPPORTED_DTYPE"
    assert caught.value.context == {"column": "value", "dtype": "int64"}


def test_filter_rows_wraps_incompatible_comparisons() -> None:
    df = pd.DataFrame({"value": [1, 2]})

    with pytest.raises(TransformationError) as caught:
        filter_rows(df, column="value", operator="greater_than", value="x")

    assert caught.value.code == "TRANSFORMATION_FILTER_FAILED"
    assert caught.value.context == {"column": "value", "operator": "greater_than"}


def test_filter_rows_is_idempotent() -> None:
    df = pd.DataFrame({"value": [1, 2, 3, None]})

    once = filter_rows(df, column="value", operator="greater_or_equal", value=2)
    twice = filter_rows(once, column="value", operator="greater_or_equal", value=2)

    assert_frame_equal(once, twice)


def test_filter_rows_handles_empty_frames() -> None:
    df = pd.DataFrame({"value": pd.Series([], dtype="Int64")})

    result = filter_rows(df, column="value", operator="equals", value=1)

    assert result.empty
    assert result.columns.tolist() == ["value"]
