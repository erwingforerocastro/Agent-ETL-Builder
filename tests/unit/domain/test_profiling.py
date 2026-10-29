"""Unit tests for profiling domain invariants."""

from __future__ import annotations

from typing import cast

import pytest

from domain.entities.profiling import (
    ChunkColumnState,
    ChunkDateState,
    ChunkNumericState,
    ChunkProfile,
    ColumnStatistics,
    MetricFamily,
    MetricResult,
    MetricScope,
    MetricStatus,
    ProfileReport,
    ProfileWarning,
    ValueCount,
)


def _metric(**overrides: object) -> MetricResult:
    values: dict[str, object] = {
        "metric": "column_completeness",
        "family": MetricFamily.COMPLETENESS,
        "scope": MetricScope.COLUMN,
        "subject": "id",
        "numerator": 1,
        "denominator": 2,
        "value": 0.5,
        "threshold": 1.0,
        "status": MetricStatus.FAIL,
        "formula": "numerator / denominator",
        "details": {"column": "id"},
    }
    values.update(overrides)
    return MetricResult(**values)  # type: ignore[arg-type]


def _report(**overrides: object) -> ProfileReport:
    values: dict[str, object] = {
        "run_id": "run-1",
        "source_id": "src_abc",
        "source_type": "csv",
        "row_count": 2,
        "chunk_count": 1,
        "chunk_size": 2,
        "approximate": False,
        "columns": (),
        "metrics": (),
    }
    values.update(overrides)
    return ProfileReport(**values)  # type: ignore[arg-type]


def test_metric_result_serializes_with_defaults() -> None:
    metric = _metric()

    assert metric.to_dict()["status"] == "fail"
    assert metric.to_dict()["details"] == {"column": "id"}


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"numerator": -1}, "numerator"),
        ({"denominator": -1}, "denominator"),
        ({"numerator": 3}, "numerator"),
        ({"value": 2.0}, "value"),
        ({"threshold": -0.1}, "threshold"),
        ({"metric": " "}, "metric"),
        ({"family": "completeness"}, "family"),
        ({"scope": "column"}, "scope"),
        ({"status": "fail"}, "status"),
        ({"approximate": 1}, "approximate"),
    ],
)
def test_metric_result_rejects_invalid_values(
    overrides: dict[str, object],
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        _metric(**overrides)


def test_value_count_markers_and_canonical_default() -> None:
    count = ValueCount(label="Ada", count=2)
    null = ValueCount(label="", count=1, is_null=True)
    empty = ValueCount(label="", count=1, is_empty=True)

    assert count.canonical == "Ada"
    assert null.canonical == "null"
    assert empty.canonical == "empty"
    with pytest.raises(ValueError, match="both null and empty"):
        ValueCount(label="", count=1, is_null=True, is_empty=True)
    with pytest.raises(ValueError, match="empty label"):
        ValueCount(label="x", count=1, is_null=True)
    with pytest.raises(ValueError, match="must use a label"):
        ValueCount(label="", count=1)


def test_chunk_state_rejects_inconsistent_counts() -> None:
    with pytest.raises(ValueError, match="count must match"):
        ChunkNumericState(count=1, total=1.0, minimum=1.0, maximum=1.0, values=())
    with pytest.raises(ValueError, match="minimum/maximum"):
        ChunkNumericState(count=1, total=1.0, minimum=2.0, maximum=2.0, values=(1.0,))
    with pytest.raises(ValueError, match="empty date state"):
        ChunkDateState(
            count=0,
            minimum_epoch=1.0,
            maximum_epoch=1.0,
            minimum="a",
            maximum="b",
        )
    with pytest.raises(ValueError, match="must provide"):
        ChunkDateState(count=1, minimum_epoch=None, maximum_epoch=None, minimum=None, maximum=None)
    with pytest.raises(ValueError, match="must not exceed"):
        ChunkDateState(
            count=1,
            minimum_epoch=2.0,
            maximum_epoch=1.0,
            minimum="b",
            maximum="a",
        )


def test_chunk_profile_rejects_duplicate_columns() -> None:
    column = ChunkColumnState(
        name="id",
        dtype="int64",
        row_count=1,
        null_count=0,
        empty_count=0,
    )

    with pytest.raises(ValueError, match="complete_rows"):
        ChunkProfile(
            chunk_index=0,
            row_count=1,
            complete_rows=2,
            columns=(column,),
        )
    with pytest.raises(ValueError, match="column names"):
        ChunkProfile(
            chunk_index=0,
            row_count=1,
            complete_rows=1,
            columns=(column, column),
        )


def test_profile_warning_and_report_serialization() -> None:
    warning = ProfileWarning(
        code="PROFILE_DISTINCT_CAPPED",
        message="capped",
        column="id",
    )
    column = ColumnStatistics(
        name="id",
        dtype="int64",
        row_count=1,
        null_count=0,
        empty_count=0,
        distinct_count=1,
    )
    report = _report(columns=(column,), warnings=(warning,))

    payload = report.to_info_dict()
    quality = cast(dict[str, object], payload["quality"])
    warnings = cast(list[dict[str, object]], quality["warnings"])
    columns = cast(list[dict[str, object]], payload["columns"])

    assert payload["schema_version"] == "1.0.0"
    assert payload["profile"]["scope"] == "full"  # type: ignore[index]
    assert warnings[0]["code"] == "PROFILE_DISTINCT_CAPPED"
    assert columns[0]["name"] == "id"
    with pytest.raises(ValueError, match="metric name/subject"):
        _report(metrics=(_metric(), _metric()))
    with pytest.raises(ValueError, match="unsupported source_type"):
        _report(source_type="xml")
    with pytest.raises(ValueError, match="content_hash"):
        _report(content_hash=" ")
