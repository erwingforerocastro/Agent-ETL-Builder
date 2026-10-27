import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from domain.errors import TransformationError
from infrastructure.transformations.drop_duplicates import drop_duplicate_rows


def test_drop_duplicate_rows_keeps_first_and_resets_index() -> None:
    df = pd.DataFrame(
        {"id": [1, 1, 2], "name": ["a", "a", "b"]},
        index=[10, 11, 12],
    )

    result = drop_duplicate_rows(df)

    expected = pd.DataFrame({"id": [1, 2], "name": ["a", "b"]})
    assert_frame_equal(result, expected)
    assert df.index.tolist() == [10, 11, 12]


def test_drop_duplicate_rows_uses_subset_and_keep_policy() -> None:
    df = pd.DataFrame({"id": [1, 1, 2], "name": ["a", "b", "c"]})

    result = drop_duplicate_rows(df, subset=["id"], keep="last")

    expected = pd.DataFrame({"id": [1, 2], "name": ["b", "c"]})
    assert_frame_equal(result, expected)


def test_drop_duplicate_rows_is_idempotent() -> None:
    df = pd.DataFrame({"id": [1, 1, 2], "name": ["a", "a", "b"]})

    once = drop_duplicate_rows(df)
    twice = drop_duplicate_rows(once)

    assert_frame_equal(once, twice)


def test_drop_duplicate_rows_rejects_missing_columns() -> None:
    df = pd.DataFrame({"id": [1, 2]})

    with pytest.raises(TransformationError) as caught:
        drop_duplicate_rows(df, subset=["missing"])

    assert caught.value.code == "TRANSFORMATION_COLUMN_NOT_FOUND"
    assert caught.value.context == {"missing_columns": ["missing"]}
    assert caught.value.module == "infrastructure.transformations.drop_duplicates"


def test_drop_duplicate_rows_rejects_empty_subset() -> None:
    df = pd.DataFrame({"id": [1, 2]})

    with pytest.raises(TransformationError) as caught:
        drop_duplicate_rows(df, subset=[])

    assert caught.value.code == "TRANSFORMATION_INVALID_PARAMETER"
    assert caught.value.context == {"parameter": "subset"}
