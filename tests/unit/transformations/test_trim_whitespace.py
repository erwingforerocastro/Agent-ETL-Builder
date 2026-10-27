from typing import cast

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from domain.errors import TransformationError
from infrastructure.transformations.trim_whitespace import TrimPolicy, trim_whitespace


def test_trim_whitespace_trims_text_and_preserves_other_values() -> None:
    df = pd.DataFrame(
        {
            "name": ["  Ada  ", " Bob", None],
            "score": [1, 2, 3],
            "mixed": [" x ", 5, None],
        }
    )

    result = trim_whitespace(df)

    assert result["name"].tolist()[:2] == ["Ada", "Bob"]
    assert pd.isna(result["name"].iloc[2])
    assert result["score"].tolist() == [1, 2, 3]
    assert result["mixed"].tolist()[0] == "x"
    assert result["mixed"].iloc[1] == 5
    assert df["name"].iloc[0] == "  Ada  "


def test_trim_whitespace_supports_leading_and_trailing_policies() -> None:
    df = pd.DataFrame({"name": ["  Ada  "]})

    leading = trim_whitespace(df, columns=["name"], policy="leading")
    trailing = trim_whitespace(df, columns=["name"], policy="trailing")

    assert leading["name"].tolist() == ["Ada  "]
    assert trailing["name"].tolist() == ["  Ada"]


def test_trim_whitespace_applies_policies_to_mixed_object_columns() -> None:
    df = pd.DataFrame({"mixed": pd.Series(["  x  ", 5], dtype=object)})

    leading = trim_whitespace(df, columns=["mixed"], policy="leading")
    trailing = trim_whitespace(df, columns=["mixed"], policy="trailing")

    assert leading["mixed"].tolist() == ["x  ", 5]
    assert trailing["mixed"].tolist() == ["  x", 5]


def test_trim_whitespace_is_idempotent() -> None:
    df = pd.DataFrame({"name": ["  Ada  ", None]})

    once = trim_whitespace(df)
    twice = trim_whitespace(once)

    assert_frame_equal(once, twice)


def test_trim_whitespace_rejects_selected_non_text_column() -> None:
    df = pd.DataFrame({"score": [1, 2]})

    with pytest.raises(TransformationError) as caught:
        trim_whitespace(df, columns=["score"])

    assert caught.value.code == "TRANSFORMATION_UNSUPPORTED_DTYPE"
    assert caught.value.context == {"column": "score", "dtype": "int64"}


def test_trim_whitespace_rejects_missing_columns() -> None:
    df = pd.DataFrame({"name": ["Ada"]})

    with pytest.raises(TransformationError) as caught:
        trim_whitespace(df, columns=["missing"])

    assert caught.value.code == "TRANSFORMATION_COLUMN_NOT_FOUND"


def test_trim_whitespace_rejects_empty_columns_and_invalid_policy() -> None:
    df = pd.DataFrame({"name": ["Ada"]})

    with pytest.raises(TransformationError) as empty:
        trim_whitespace(df, columns=[])
    with pytest.raises(TransformationError) as invalid:
        trim_whitespace(df, policy=cast(TrimPolicy, "sideways"))

    assert empty.value.code == "TRANSFORMATION_INVALID_PARAMETER"
    assert invalid.value.context == {"parameter": "policy"}
