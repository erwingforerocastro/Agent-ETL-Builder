from typing import cast

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from domain.errors import TransformationError
from infrastructure.transformations.change_text_case import TextCase, change_text_case


def test_change_text_case_applies_to_text_columns_only() -> None:
    df = pd.DataFrame(
        {
            "name": ["Ada", None],
            "score": [1, 2],
            "mixed": [" X ", 5],
        }
    )

    result = change_text_case(df)

    assert result["name"].tolist()[0] == "ada"
    assert pd.isna(result["name"].iloc[1])
    assert result["score"].tolist() == [1, 2]
    assert result["mixed"].tolist() == [" x ", 5]
    assert df["name"].iloc[0] == "Ada"


def test_change_text_case_supports_upper_and_title() -> None:
    df = pd.DataFrame({"name": ["ada lovelace", "Grace Hopper"]})

    upper = change_text_case(df, columns=["name"], case="upper")
    title = change_text_case(df, columns=["name"], case="title")

    assert upper["name"].tolist() == ["ADA LOVELACE", "GRACE HOPPER"]
    assert title["name"].tolist() == ["Ada Lovelace", "Grace Hopper"]


def test_change_text_case_preserves_non_string_values_in_object_columns() -> None:
    df = pd.DataFrame({"mixed": pd.Series([" Ada ", 5], dtype=object)})

    result = change_text_case(df, columns=["mixed"], case="upper")

    assert result["mixed"].tolist() == [" ADA ", 5]


def test_change_text_case_supports_title_case_on_object_columns() -> None:
    df = pd.DataFrame({"name": pd.Series(["ada lovelace", None], dtype=object)})

    result = change_text_case(df, columns=["name"], case="title")

    assert result["name"].iloc[0] == "Ada Lovelace"
    assert pd.isna(result["name"].iloc[1])


def test_change_text_case_rejects_selected_non_text_column() -> None:
    df = pd.DataFrame({"score": [1, 2]})

    with pytest.raises(TransformationError) as caught:
        change_text_case(df, columns=["score"])

    assert caught.value.code == "TRANSFORMATION_UNSUPPORTED_DTYPE"
    assert caught.value.context == {"column": "score", "dtype": "int64"}


def test_change_text_case_rejects_missing_columns_and_invalid_parameters() -> None:
    df = pd.DataFrame({"name": ["Ada"]})

    with pytest.raises(TransformationError) as missing:
        change_text_case(df, columns=["missing"])
    with pytest.raises(TransformationError) as empty:
        change_text_case(df, columns=[])
    with pytest.raises(TransformationError) as invalid:
        change_text_case(df, case=cast(TextCase, "capitalize"))

    assert missing.value.code == "TRANSFORMATION_COLUMN_NOT_FOUND"
    assert empty.value.context == {"parameter": "columns"}
    assert invalid.value.context == {"parameter": "case"}


def test_change_text_case_is_idempotent() -> None:
    df = pd.DataFrame({"name": ["Ada", None]})

    once = change_text_case(df)
    twice = change_text_case(once)

    assert_frame_equal(once, twice)


def test_change_text_case_handles_empty_frames() -> None:
    df = pd.DataFrame({"name": pd.Series([], dtype="string")})

    result = change_text_case(df)

    assert result.empty
    assert result.columns.tolist() == ["name"]
