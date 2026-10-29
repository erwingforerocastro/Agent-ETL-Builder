from typing import cast

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from domain.errors import TransformationError
from infrastructure.transformations.normalize_dates import DateParseMode, normalize_dates


def test_normalize_dates_parses_and_formats_text_values() -> None:
    df = pd.DataFrame({"created_at": ["2026-01-02", "2026-12-31", None]})

    result = normalize_dates(
        df,
        column="created_at",
        output_format="%Y-%m-%d",
    )

    assert result["created_at"].tolist()[:2] == ["2026-01-02", "2026-12-31"]
    assert pd.isna(result["created_at"].iloc[2])
    assert df["created_at"].iloc[0] == "2026-01-02"


def test_normalize_dates_formats_existing_datetime_columns() -> None:
    df = pd.DataFrame({"created_at": pd.to_datetime(["2026-01-02", "2026-12-31"])})

    result = normalize_dates(
        df,
        column="created_at",
        output_format="%d/%m/%Y",
    )

    assert result["created_at"].tolist() == ["02/01/2026", "31/12/2026"]


def test_normalize_dates_coerces_invalid_values() -> None:
    df = pd.DataFrame({"created_at": ["2026-01-02", "not-a-date"]})

    result = normalize_dates(
        df,
        column="created_at",
        output_format="%Y-%m-%d",
        errors="coerce",
    )

    assert result["created_at"].iloc[0] == "2026-01-02"
    assert pd.isna(result["created_at"].iloc[1])


def test_normalize_dates_reports_invalid_value_count() -> None:
    df = pd.DataFrame({"created_at": ["2026-01-02", "not-a-date", None]})

    with pytest.raises(TransformationError) as caught:
        normalize_dates(
            df,
            column="created_at",
            output_format="%Y-%m-%d",
        )

    assert caught.value.code == "TRANSFORMATION_DATE_PARSE_FAILED"
    assert caught.value.context == {"column": "created_at", "invalid_count": 1}


def test_normalize_dates_rejects_non_date_columns() -> None:
    df = pd.DataFrame({"created_at": [1, 2]})

    with pytest.raises(TransformationError) as caught:
        normalize_dates(
            df,
            column="created_at",
            output_format="%Y-%m-%d",
        )

    assert caught.value.code == "TRANSFORMATION_UNSUPPORTED_DTYPE"
    assert caught.value.context == {"column": "created_at", "dtype": "int64"}


def test_normalize_dates_rejects_invalid_parameters() -> None:
    df = pd.DataFrame({"created_at": ["2026-01-02"]})

    with pytest.raises(TransformationError) as blank_format:
        normalize_dates(df, column="created_at", output_format="  ")
    with pytest.raises(TransformationError) as invalid_mode:
        normalize_dates(
            df,
            column="created_at",
            output_format="%Y-%m-%d",
            errors=cast(DateParseMode, "ignore"),
        )

    assert blank_format.value.context == {"parameter": "output_format"}
    assert invalid_mode.value.context == {"parameter": "errors"}


def test_normalize_dates_rejects_missing_column() -> None:
    df = pd.DataFrame({"created_at": ["2026-01-02"]})

    with pytest.raises(TransformationError) as caught:
        normalize_dates(df, column="missing", output_format="%Y-%m-%d")

    assert caught.value.code == "TRANSFORMATION_COLUMN_NOT_FOUND"


def test_normalize_dates_is_idempotent() -> None:
    df = pd.DataFrame({"created_at": ["2026-01-02", None]})

    once = normalize_dates(df, column="created_at", output_format="%Y-%m-%d")
    twice = normalize_dates(once, column="created_at", output_format="%Y-%m-%d")

    assert_frame_equal(once, twice)


def test_normalize_dates_handles_empty_frames() -> None:
    df = pd.DataFrame({"created_at": pd.Series([], dtype="string")})

    result = normalize_dates(df, column="created_at", output_format="%Y-%m-%d")

    assert result.empty
    assert result.columns.tolist() == ["created_at"]
