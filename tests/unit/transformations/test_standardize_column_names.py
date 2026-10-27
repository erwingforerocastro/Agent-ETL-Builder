from typing import cast

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from domain.errors import TransformationError
from infrastructure.transformations.standardize_column_names import (
    ColumnCase,
    standardize_column_names,
)


def test_standardize_column_names_normalizes_text_and_case() -> None:
    df = pd.DataFrame(
        {
            " First Name ": ["Ada"],
            "Order-ID": [1],
            "Cafe\u0301": ["yes"],
            "2Value": [2],
        }
    )

    result = standardize_column_names(df)

    assert result.columns.tolist() == ["first_name", "order_id", "café", "2value"]
    assert df.columns.tolist() == [" First Name ", "Order-ID", "Cafe\u0301", "2Value"]


def test_standardize_column_names_supports_upper_and_preserve() -> None:
    df = pd.DataFrame({"First Name": ["Ada"]})

    upper = standardize_column_names(df, case="upper")
    preserved = standardize_column_names(df, case="preserve")

    assert upper.columns.tolist() == ["FIRST_NAME"]
    assert preserved.columns.tolist() == ["First_Name"]


def test_standardize_column_names_is_idempotent() -> None:
    df = pd.DataFrame({" First Name ": ["Ada"]})

    once = standardize_column_names(df)
    twice = standardize_column_names(once)

    assert_frame_equal(once, twice)


def test_standardize_column_names_rejects_blank_names() -> None:
    df = pd.DataFrame({"!!!": [1]})

    with pytest.raises(TransformationError) as caught:
        standardize_column_names(df)

    assert caught.value.code == "TRANSFORMATION_INVALID_COLUMN_NAME"
    assert caught.value.context == {"column_index": 0}


def test_standardize_column_names_rejects_normalized_collisions() -> None:
    df = pd.DataFrame({"First Name": [1], "first-name": [2]})

    with pytest.raises(TransformationError) as caught:
        standardize_column_names(df)

    assert caught.value.code == "TRANSFORMATION_DUPLICATE_COLUMN_NAME"
    assert caught.value.context == {
        "normalized_name": "first_name",
        "column_indices": [0, 1],
    }


def test_standardize_column_names_rejects_duplicate_original_columns() -> None:
    df = pd.DataFrame([[1, 2]], columns=["a", "a"])

    with pytest.raises(TransformationError) as caught:
        standardize_column_names(df)

    assert caught.value.code == "TRANSFORMATION_DUPLICATE_COLUMN_NAME"
    assert caught.value.context == {"duplicate_columns": ["a"]}


def test_standardize_column_names_rejects_multiindex_columns() -> None:
    columns = pd.MultiIndex.from_tuples([("a", "b")])
    df = pd.DataFrame([[1]], columns=columns)

    with pytest.raises(TransformationError) as caught:
        standardize_column_names(df)

    assert caught.value.code == "TRANSFORMATION_UNSUPPORTED_DTYPE"


def test_standardize_column_names_rejects_invalid_case_policy() -> None:
    df = pd.DataFrame({"First Name": [1]})

    with pytest.raises(TransformationError) as caught:
        standardize_column_names(df, case=cast(ColumnCase, "title"))

    assert caught.value.context == {"parameter": "case"}
