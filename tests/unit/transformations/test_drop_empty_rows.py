import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from domain.errors import TransformationError
from infrastructure.transformations.drop_empty_rows import drop_empty_rows


def test_drop_empty_rows_removes_null_blank_and_whitespace_rows() -> None:
    df = pd.DataFrame(
        {
            "a": [" ", None, "x", ""],
            "b": [None, "", "y", "  "],
            "c": ["", " ", "z", None],
        }
    )

    result = drop_empty_rows(df)

    expected = pd.DataFrame({"a": ["x"], "b": ["y"], "c": ["z"]})
    assert_frame_equal(result, expected)
    assert len(df) == 4


def test_drop_empty_rows_uses_only_selected_columns() -> None:
    df = pd.DataFrame(
        {
            "name": ["", "Ada"],
            "note": ["ignored", None],
        }
    )

    result = drop_empty_rows(df, subset=["name"])

    assert result["name"].tolist() == ["Ada"]
    assert result["note"].isna().all()
    assert len(result) == 1


def test_drop_empty_rows_handles_numeric_columns() -> None:
    df = pd.DataFrame({"id": [None, 1.0], "name": ["", "Ada"]})

    result = drop_empty_rows(df)

    assert result["id"].tolist() == [1.0]
    assert result["name"].tolist() == ["Ada"]


def test_drop_empty_rows_returns_a_copy_when_there_are_no_columns() -> None:
    df = pd.DataFrame(index=[0, 1])

    result = drop_empty_rows(df)

    assert_frame_equal(result, df)
    assert result is not df


def test_drop_empty_rows_keeps_rows_with_one_non_blank_value() -> None:
    df = pd.DataFrame({"a": [None, None], "b": ["value", ""]})

    result = drop_empty_rows(df)

    expected = pd.DataFrame({"a": [None], "b": ["value"]})
    assert_frame_equal(result, expected)


def test_drop_empty_rows_rejects_missing_columns() -> None:
    df = pd.DataFrame({"id": [1, 2]})

    with pytest.raises(TransformationError) as caught:
        drop_empty_rows(df, subset=["missing"])

    assert caught.value.code == "TRANSFORMATION_COLUMN_NOT_FOUND"


def test_drop_empty_rows_rejects_empty_subset() -> None:
    df = pd.DataFrame({"id": [1, 2]})

    with pytest.raises(TransformationError) as caught:
        drop_empty_rows(df, subset=[])

    assert caught.value.code == "TRANSFORMATION_INVALID_PARAMETER"
