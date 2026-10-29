from typing import cast

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from domain.errors import TransformationError
from infrastructure.transformations.replace_values import replace_values


def test_replace_values_replaces_exact_matches_only() -> None:
    df = pd.DataFrame({"status": ["N/A", "NA", "N/A extra", None]})

    result = replace_values(df, columns=["status"], old="N/A", new="unknown")

    assert result["status"].tolist()[:3] == ["unknown", "NA", "N/A extra"]
    assert pd.isna(result["status"].iloc[3])
    assert df["status"].iloc[0] == "N/A"


def test_replace_values_can_replace_matches_with_null() -> None:
    df = pd.DataFrame({"status": ["N/A", "ok", None]})

    result = replace_values(df, columns=["status"], old="N/A", new=None)

    assert pd.isna(result["status"].iloc[0])
    assert result["status"].iloc[1] == "ok"


def test_replace_values_applies_to_all_text_columns_by_default() -> None:
    df = pd.DataFrame(
        {
            "first": ["x", "y"],
            "second": ["x", 1],
            "count": [1, 2],
        }
    )

    result = replace_values(df, old="x", new="z")

    assert result["first"].tolist() == ["z", "y"]
    assert result["second"].tolist() == ["z", 1]
    assert result["count"].tolist() == [1, 2]


def test_replace_values_can_remove_blank_text() -> None:
    df = pd.DataFrame({"status": ["", "ok", None]})

    result = replace_values(df, columns=["status"], old="", new=None)

    assert pd.isna(result["status"].iloc[0])
    assert result["status"].iloc[1] == "ok"


def test_replace_values_rejects_selected_non_text_column() -> None:
    df = pd.DataFrame({"count": [1, 2]})

    with pytest.raises(TransformationError) as caught:
        replace_values(df, columns=["count"], old="1", new="one")

    assert caught.value.code == "TRANSFORMATION_UNSUPPORTED_DTYPE"
    assert caught.value.context == {"column": "count", "dtype": "int64"}


def test_replace_values_rejects_missing_columns_and_invalid_parameters() -> None:
    df = pd.DataFrame({"status": ["ok"]})

    with pytest.raises(TransformationError) as missing:
        replace_values(df, columns=["missing"], old="ok", new="fine")
    with pytest.raises(TransformationError) as empty:
        replace_values(df, columns=[], old="ok", new="fine")
    with pytest.raises(TransformationError) as old_type:
        replace_values(df, old=cast(str, 1), new="fine")
    with pytest.raises(TransformationError) as new_type:
        replace_values(df, old="ok", new=cast(str, 1))

    assert missing.value.code == "TRANSFORMATION_COLUMN_NOT_FOUND"
    assert empty.value.context == {"parameter": "columns"}
    assert old_type.value.context == {"parameter": "old"}
    assert new_type.value.context == {"parameter": "new"}


def test_replace_values_is_idempotent() -> None:
    df = pd.DataFrame({"status": ["N/A", "ok", None]})

    once = replace_values(df, columns=["status"], old="N/A", new="unknown")
    twice = replace_values(once, columns=["status"], old="N/A", new="unknown")

    assert_frame_equal(once, twice)


def test_replace_values_handles_empty_frames() -> None:
    df = pd.DataFrame({"status": pd.Series([], dtype="string")})

    result = replace_values(df, columns=["status"], old="N/A", new=None)

    assert result.empty
    assert result.columns.tolist() == ["status"]
