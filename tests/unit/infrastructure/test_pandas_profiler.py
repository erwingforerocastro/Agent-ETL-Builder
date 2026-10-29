"""Unit tests for mergeable pandas profiling."""

from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest

import infrastructure.profiling.pandas_profiler as profiler_module
from application.profiling.models import ProfileLimits, ProfileRequest
from domain.entities.profiling import (
    MetricFamily,
    MetricResult,
    MetricStatus,
    ProfileReport,
)
from domain.errors import ProfilingError
from infrastructure.profiling.pandas_profiler import PandasChunkProfiler


def _request(*, content_hash: str | None = None) -> ProfileRequest:
    return ProfileRequest(
        run_id="run-1",
        source_id="src_abc",
        source_type="csv",
        chunk_size=2,
        content_hash=content_hash,
    )


def _profile(
    *frames: pd.DataFrame,
    request: ProfileRequest | None = None,
    limits: ProfileLimits | None = None,
) -> ProfileReport:
    profiler = PandasChunkProfiler(limits)
    records = [
        profiler.profile_chunk(frame, chunk_index=index) for index, frame in enumerate(frames)
    ]
    return profiler.merge(records, request=request or _request())


def _metric(report: ProfileReport, metric: str, subject: str = "*") -> MetricResult:
    matches = [item for item in report.metrics if item.metric == metric and item.subject == subject]
    assert len(matches) == 1
    return matches[0]


def test_merge_completeness_uniqueness_and_accuracy() -> None:
    first = pd.DataFrame(
        {
            "id": [1, 2],
            "name": ["Ada", ""],
            "amount": [10.0, None],
        }
    )
    second = pd.DataFrame(
        {
            "id": [2, 3],
            "name": ["Bob", "Cyd"],
            "amount": [30.0, 40.0],
        }
    )

    report = _profile(first, second)

    assert report.row_count == 4
    assert report.chunk_count == 2
    assert report.approximate is False
    assert report.schema_hash is not None
    assert report.schema_hash.startswith("sha256:")
    assert report.content_hash is None
    assert _metric(report, "column_completeness", "name").numerator == 3
    assert _metric(report, "column_completeness", "name").denominator == 4
    assert _metric(report, "row_completeness").value == 0.75
    assert _metric(report, "dataset_completeness").value == 10 / 12
    assert _metric(report, "duplicate_rows").value == 1.0
    assert _metric(report, "column_uniqueness", "id").value == 0.75
    assert _metric(report, "column_uniqueness", "name").value == 1.0
    assert _metric(report, "accuracy").status is MetricStatus.NOT_APPLICABLE
    assert _metric(report, "accuracy").value is None
    assert _metric(report, "accuracy").family is MetricFamily.ACCURACY
    assert _metric(report, "consistency.rules").status is MetricStatus.NOT_APPLICABLE
    assert _metric(report, "validity.rules").status is MetricStatus.NOT_APPLICABLE


def test_numeric_merge_uses_exact_values_not_medians_of_medians() -> None:
    first = pd.DataFrame({"x": [1.0, 100.0, float("nan"), float("inf")]})
    second = pd.DataFrame({"x": [2.0, 3.0]})

    report = _profile(first, second)

    column = report.columns[0]
    assert column.numeric is not None
    assert column.numeric.count == 4
    assert column.numeric.total == 106.0
    assert column.numeric.mean == 26.5
    assert column.numeric.median == 2.5
    assert column.numeric.minimum == 1.0
    assert column.numeric.maximum == 100.0
    assert column.numeric.non_finite_count == 1
    assert column.numeric.mode == (1.0, 2.0, 3.0, 100.0)
    assert _metric(report, "column_completeness", "x").numerator == 5


def test_numeric_mode_can_be_multi_valued() -> None:
    frame = pd.DataFrame({"x": [1.0, 1.0, 2.0, 2.0]})

    report = _profile(frame)

    column = report.columns[0]
    assert column.numeric is not None
    assert column.numeric.mode == (1.0, 2.0)


def test_dates_merge_min_max_range_and_utc() -> None:
    first = pd.DataFrame(
        {
            "created": pd.to_datetime(
                pd.Series(["2026-01-02", "2026-01-01", None]),
            )
        }
    )
    second = pd.DataFrame(
        {
            "created": pd.to_datetime(
                pd.Series(["2026-01-04", None]),
            )
        }
    )
    utc = pd.DataFrame(
        {
            "created": pd.to_datetime(
                ["2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"],
                utc=True,
            )
        }
    )

    report = _profile(first, second)
    utc_report = _profile(utc)

    dates = report.columns[0].dates
    utc_dates = utc_report.columns[0].dates
    assert dates is not None
    assert dates.count == 3
    assert dates.minimum == "2026-01-01T00:00:00"
    assert dates.maximum == "2026-01-04T00:00:00"
    assert dates.range_seconds == 259_200.0
    assert dates.timezone is None
    assert utc_dates is not None
    assert utc_dates.minimum == "2026-01-01T00:00:00+00:00"
    assert utc_dates.timezone == "UTC"


def test_categorical_frequencies_include_null_and_empty_categories() -> None:
    first = pd.DataFrame({"category": pd.Series(["a", "b", ""], dtype="str")})
    second = pd.DataFrame({"category": pd.Series(["a", None, "a"], dtype="str")})

    report = _profile(first, second)

    categorical = report.columns[0].categorical
    assert categorical is not None
    counts = {
        (item.label, item.is_null, item.is_empty): item.count for item in categorical.frequencies
    }
    assert counts[("a", False, False)] == 3
    assert counts[("b", False, False)] == 1
    assert counts[("", True, False)] == 1
    assert counts[("", False, True)] == 1
    assert categorical.distinct_count == 2
    assert report.columns[0].present_count == 4


def test_caps_mark_results_approximate_and_emit_warnings() -> None:
    frame = pd.DataFrame({"category": ["a", "b", "c", "d"]})
    limits = ProfileLimits(max_tracked_values=2, max_frequency_rows=1)

    report = _profile(frame, limits=limits)

    column = report.columns[0]
    uniqueness = _metric(report, "column_uniqueness", "category")
    duplicates = _metric(report, "duplicate_rows")
    assert column.distinct_capped is True
    assert column.categorical is not None
    assert column.categorical.capped is True
    assert column.categorical.truncated is True
    assert uniqueness.approximate is True
    assert uniqueness.status is MetricStatus.FAIL
    assert duplicates.approximate is True
    assert report.approximate is True
    assert {warning.code for warning in report.warnings} >= {
        "PROFILE_DISTINCT_CAPPED",
        "PROFILE_FREQUENCY_TABLE_TRUNCATED",
        "PROFILE_ROW_HASHES_CAPPED",
    }


def test_merge_caps_distinct_and_row_hash_maps_across_chunks() -> None:
    first = pd.DataFrame({"category": ["a", "b"]})
    second = pd.DataFrame({"category": ["c", "d"]})
    limits = ProfileLimits(max_tracked_values=2, max_frequency_rows=10)

    report = _profile(first, second, limits=limits)

    assert report.columns[0].distinct_count == 2
    assert report.columns[0].distinct_capped is True
    assert _metric(report, "column_uniqueness", "category").approximate is True
    assert _metric(report, "duplicate_rows").approximate is True
    assert report.approximate is True
    assert {warning.code for warning in report.warnings} >= {
        "PROFILE_DISTINCT_CAPPED",
        "PROFILE_ROW_HASHES_CAPPED",
    }


def test_empty_source_and_all_null_column() -> None:
    empty_report = PandasChunkProfiler().merge([], request=_request())
    null_frame = pd.DataFrame({"only": [None, None]})
    null_report = _profile(null_frame)

    assert empty_report.row_count == 0
    assert empty_report.columns == ()
    assert _metric(empty_report, "accuracy").value is None
    assert _metric(empty_report, "duplicate_rows").status is MetricStatus.NOT_APPLICABLE
    assert null_report.row_count == 2
    assert _metric(null_report, "column_completeness", "only").value == 0.0
    assert null_report.columns[0].categorical is not None
    assert null_report.columns[0].categorical.frequencies[0].is_null is True


def test_empty_chunk_preserves_schema() -> None:
    frame = pd.DataFrame({"id": pd.Series([], dtype="int64")})

    report = _profile(frame)

    assert report.row_count == 0
    assert report.columns[0].name == "id"
    assert report.columns[0].numeric is not None
    assert report.columns[0].numeric.count == 0
    assert _metric(report, "column_completeness", "id").status is MetricStatus.NOT_APPLICABLE


def test_duplicate_missing_and_invalid_chunk_records_are_rejected() -> None:
    request = _request()
    profiler = PandasChunkProfiler()
    record = profiler.profile_chunk(pd.DataFrame({"id": [1]}), chunk_index=0)

    with pytest.raises(ProfilingError) as duplicate:
        profiler.merge([record, replace(record)], request=request)
    with pytest.raises(ProfilingError) as missing:
        profiler.merge([replace(record, chunk_index=1)], request=request)
    with pytest.raises(ProfilingError) as invalid:
        profiler.merge([object()], request=request)  # type: ignore[list-item]

    assert duplicate.value.code == "PROFILE_CHUNK_SEQUENCE_INVALID"
    assert missing.value.code == "PROFILE_CHUNK_SEQUENCE_INVALID"
    assert invalid.value.code == "PROFILE_CHUNK_INVALID"


def test_schema_drift_is_rejected() -> None:
    profiler = PandasChunkProfiler()
    request = _request()
    first = profiler.profile_chunk(pd.DataFrame({"id": [1]}), chunk_index=0)
    other = profiler.profile_chunk(pd.DataFrame({"other": [1]}), chunk_index=1)
    categorical = profiler.profile_chunk(pd.DataFrame({"id": ["a"]}), chunk_index=1)
    naive = profiler.profile_chunk(
        pd.DataFrame({"id": pd.to_datetime(["2026-01-01"])}),
        chunk_index=0,
    )
    aware = profiler.profile_chunk(
        pd.DataFrame({"id": pd.to_datetime(["2026-01-02"], utc=True)}),
        chunk_index=1,
    )

    with pytest.raises(ProfilingError) as names:
        profiler.merge([first, other], request=request)
    with pytest.raises(ProfilingError) as types:
        profiler.merge([first, categorical], request=request)
    with pytest.raises(ProfilingError) as timezone:
        profiler.merge([naive, aware], request=request)

    assert names.value.code == "PROFILE_SCHEMA_DRIFT"
    assert types.value.code == "PROFILE_SCHEMA_DRIFT"
    assert timezone.value.code == "PROFILE_SCHEMA_DRIFT"


def test_compatible_numeric_and_all_null_dtype_drift_is_merged() -> None:
    first = pd.DataFrame({"amount": [1, 2], "note": ["ok", "fine"]})
    second = pd.DataFrame({"amount": [3.5, 4.5], "note": [None, None]})

    report = _profile(first, second)

    amount, note = report.columns
    assert amount.numeric is not None
    assert amount.numeric.count == 4
    assert amount.dtype == "float64|int64"
    assert note.categorical is not None
    assert note.null_count == 2
    assert note.distinct_count == 2


def test_invalid_chunk_and_index_are_rejected() -> None:
    profiler = PandasChunkProfiler()

    with pytest.raises(ProfilingError) as invalid_chunk:
        profiler.profile_chunk([1, 2], chunk_index=0)
    with pytest.raises(ProfilingError) as invalid_index:
        profiler.profile_chunk(pd.DataFrame({"id": [1]}), chunk_index=-1)

    assert invalid_chunk.value.code == "PROFILE_INVALID_CHUNK"
    assert invalid_index.value.code == "PROFILE_CHUNK_INDEX_INVALID"


def test_column_failure_is_structured(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_column(series: pd.Series, *, name: str, limit: int) -> object:
        del series, name, limit
        raise RuntimeError("boom")

    monkeypatch.setattr(profiler_module, "_profile_column", fail_column)

    with pytest.raises(ProfilingError) as caught:
        PandasChunkProfiler().profile_chunk(
            pd.DataFrame({"id": [1]}),
            chunk_index=0,
        )

    assert caught.value.code == "PROFILE_COLUMN_FAILED"
    assert caught.value.context["column"] == "id"


def test_unhashable_values_fall_back_to_canonical_row_hashes() -> None:
    frame = pd.DataFrame({"payload": [{"a": 1}, {"a": 1}, {"b": [2, 3]}]})

    report = _profile(frame)

    assert _metric(report, "duplicate_rows").numerator == 2
    assert _metric(report, "duplicate_rows").denominator == 3
    assert report.columns[0].distinct_count == 2


def test_mixed_mapping_keys_are_safe() -> None:
    frame = pd.DataFrame({"payload": [{"a": 1}, {1: 2}]})

    report = _profile(frame)

    assert report.row_count == 2
    assert report.columns[0].distinct_count == 2


def test_duplicate_columns_are_rejected() -> None:
    frame = pd.DataFrame([[1, 2]], columns=["x", "x"])

    with pytest.raises(ProfilingError) as caught:
        PandasChunkProfiler().profile_chunk(frame, chunk_index=0)

    assert caught.value.code == "PROFILE_DUPLICATE_COLUMN_NAME"


def test_profile_report_records_content_hash() -> None:
    report = _profile(
        pd.DataFrame({"id": [1]}),
        request=_request(content_hash="sha256:abc"),
    )

    assert report.content_hash == "sha256:abc"
