"""Unit tests for mergeable pandas profiling."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

import infrastructure.profiling.pandas_profiler as profiler_module
from application.profiling.models import ProfileLimits, ProfileRequest, ProfileThresholds
from domain.entities.profiling import (
    MetricFamily,
    MetricResult,
    MetricScope,
    MetricStatus,
    ProfileReport,
    ProfileScope,
    QualityRule,
    RuleKind,
)
from domain.errors import ProfilingError
from infrastructure.profiling.pandas_profiler import PandasChunkProfiler
from infrastructure.profiling.spill import FilesystemNumericSpillStore


def _request(
    *,
    rules: tuple[QualityRule, ...] = (),
    limits: ProfileLimits | None = None,
    thresholds: ProfileThresholds | None = None,
    scope: ProfileScope = ProfileScope.FULL,
    approximate: bool = False,
) -> ProfileRequest:
    return ProfileRequest(
        run_id="run-1",
        source_id="src_abc",
        source_type="csv",
        chunk_size=2,
        scope=scope,
        approximate=approximate,
        rules=rules,
        limits=limits or ProfileLimits(),
        thresholds=thresholds or ProfileThresholds(),
    )


def _profile(
    *frames: pd.DataFrame,
    request: ProfileRequest,
) -> ProfileReport:
    profiler = PandasChunkProfiler()
    records = [
        profiler.profile_chunk(frame, chunk_index=index, request=request)
        for index, frame in enumerate(frames)
    ]
    return profiler.merge(records, request=request)


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

    report = _profile(first, second, request=_request())

    assert report.row_count == 4
    assert report.chunk_count == 2
    assert report.approximate is False
    assert report.schema_hash is not None
    assert report.schema_hash.startswith("sha256:")
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

    report = _profile(first, second, request=_request())

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

    report = _profile(frame, request=_request())

    column = report.columns[0]
    assert column.numeric is not None
    assert column.numeric.mode == (1.0, 2.0)


def test_spilled_numeric_values_merge_to_exact_statistics(tmp_path: Path) -> None:
    spill = FilesystemNumericSpillStore(tmp_path / "spill")
    request = _request()
    profiler = PandasChunkProfiler(spill)
    first = profiler.profile_chunk(
        pd.DataFrame({"x": [1.0, 100.0]}),
        chunk_index=0,
        request=request,
    )
    second = profiler.profile_chunk(
        pd.DataFrame({"x": [2.0, 3.0]}),
        chunk_index=1,
        request=request,
    )

    report = profiler.merge([first, second], request=request)

    assert first.columns[0].numeric is not None
    assert first.columns[0].numeric.values == ()
    assert first.columns[0].numeric.values_ref is not None
    assert (tmp_path / "spill" / first.columns[0].numeric.values_ref).exists()
    numeric = report.columns[0].numeric
    assert numeric is not None
    assert numeric.median == 2.5
    assert numeric.mean == 26.5
    assert numeric.mode == (1.0, 2.0, 3.0, 100.0)
    assert numeric.approximate is False


def test_spill_rejects_unsafe_identifiers_before_writing(tmp_path: Path) -> None:
    spill = FilesystemNumericSpillStore(tmp_path / "spill")
    request = replace(_request(), run_id="../run")

    with pytest.raises(ProfilingError) as caught:
        PandasChunkProfiler(spill).profile_chunk(
            pd.DataFrame({"x": [1.0]}),
            chunk_index=0,
            request=request,
        )

    assert caught.value.code == "PROFILE_ARTIFACT_PATH_INVALID"
    assert not (tmp_path / "spill").exists()


def test_spilled_values_require_the_same_spill_store(tmp_path: Path) -> None:
    spill = FilesystemNumericSpillStore(tmp_path / "spill")
    request = _request()
    record = PandasChunkProfiler(spill).profile_chunk(
        pd.DataFrame({"x": [1.0, 2.0]}),
        chunk_index=0,
        request=request,
    )

    with pytest.raises(ProfilingError) as caught:
        PandasChunkProfiler().merge([record], request=request)

    assert caught.value.code == "PROFILE_SPILL_UNAVAILABLE"


def test_numeric_mode_cap_is_approximate_and_warned(tmp_path: Path) -> None:
    spill = FilesystemNumericSpillStore(tmp_path / "spill")
    request = _request(
        limits=ProfileLimits(
            max_distinct_values=1,
            max_row_hashes=100,
            max_frequency_rows=10,
        )
    )
    profiler = PandasChunkProfiler(spill)
    record = profiler.profile_chunk(
        pd.DataFrame({"x": [1.0, 2.0, 3.0]}),
        chunk_index=0,
        request=request,
    )
    report = profiler.merge([record], request=request)

    numeric = report.columns[0].numeric
    assert numeric is not None
    assert numeric.approximate is True
    assert numeric.median == 2.0
    assert numeric.mode == ()
    assert report.approximate is True
    assert "PROFILE_NUMERIC_MODE_CAPPED" in {warning.code for warning in report.warnings}


def test_spill_reference_outside_the_root_is_rejected(tmp_path: Path) -> None:
    spill = FilesystemNumericSpillStore(tmp_path / "spill")

    with pytest.raises(ProfilingError) as caught:
        list(spill.iter_values("../outside.parquet"))

    assert caught.value.code == "PROFILE_SPILL_REF_INVALID"


def test_missing_spill_file_is_a_structured_error(tmp_path: Path) -> None:
    spill = FilesystemNumericSpillStore(tmp_path / "spill")
    request = _request()
    profiler = PandasChunkProfiler(spill)
    record = profiler.profile_chunk(
        pd.DataFrame({"x": [1.0, 2.0]}),
        chunk_index=0,
        request=request,
    )
    numeric = record.columns[0].numeric
    assert numeric is not None
    assert numeric.values_ref is not None
    (tmp_path / "spill" / numeric.values_ref).unlink()

    with pytest.raises(ProfilingError) as caught:
        profiler.merge([record], request=request)

    assert caught.value.code == "PROFILE_SPILL_READ_FAILED"


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

    report = _profile(first, second, request=_request())
    utc_report = _profile(utc, request=_request())

    dates = report.columns[0].dates
    utc_dates = utc_report.columns[0].dates
    assert dates is not None
    assert dates.count == 3
    assert dates.minimum == "2026-01-01T00:00:00"
    assert dates.maximum == "2026-01-04T00:00:00"
    assert dates.range_seconds == 259_200.0
    assert dates.range_iso == "P3D"
    assert dates.timezone is None
    assert utc_dates is not None
    assert utc_dates.minimum == "2026-01-01T00:00:00+00:00"
    assert utc_dates.timezone == "UTC"


def test_date_range_uses_iso_duration_for_sub_day_ranges() -> None:
    frame = pd.DataFrame(
        {
            "created": pd.to_datetime(
                pd.Series(["2026-01-01T01:00:00", "2026-01-01T02:30:00"]),
            )
        }
    )

    report = _profile(frame, request=_request())

    dates = report.columns[0].dates
    assert dates is not None
    assert dates.range_seconds == 5_400.0
    assert dates.range_iso == "PT1H30M0S"


def test_categorical_frequencies_include_null_and_empty_categories() -> None:
    first = pd.DataFrame({"category": pd.Series(["a", "b", ""], dtype="str")})
    second = pd.DataFrame({"category": pd.Series(["a", None, "a"], dtype="str")})

    report = _profile(first, second, request=_request())

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
    request = _request(
        limits=ProfileLimits(
            max_distinct_values=2,
            max_row_hashes=2,
            max_frequency_rows=1,
        )
    )

    report = _profile(frame, request=request)

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
    request = _request(
        limits=ProfileLimits(
            max_distinct_values=2,
            max_row_hashes=2,
            max_frequency_rows=10,
        )
    )

    report = _profile(first, second, request=request)

    assert report.columns[0].distinct_count == 2
    assert report.columns[0].distinct_capped is True
    assert _metric(report, "column_uniqueness", "category").approximate is True
    assert _metric(report, "duplicate_rows").approximate is True
    assert report.approximate is True
    assert {warning.code for warning in report.warnings} >= {
        "PROFILE_DISTINCT_CAPPED",
        "PROFILE_ROW_HASHES_CAPPED",
    }


def test_declared_rules_merge_to_consistent_validity_and_key_metrics() -> None:
    first = pd.DataFrame(
        {
            "code": ["A1", "B2"],
            "amount": [1, 10],
            "start": [1, 2],
            "end": [1, 3],
            "key": [1, 1],
        }
    )
    second = pd.DataFrame(
        {
            "code": ["bad", "A1"],
            "amount": [20, 30],
            "start": [3, 4],
            "end": [2, 5],
            "key": [2, 3],
        }
    )
    rules = (
        QualityRule(
            rule_id="code_pattern",
            kind=RuleKind.REGEX,
            columns=("code",),
            pattern=r"^[A-Z]\d$",
        ),
        QualityRule(
            rule_id="amount_range",
            kind=RuleKind.RANGE,
            columns=("amount",),
            minimum=0,
            maximum=15,
            threshold=0.5,
        ),
        QualityRule(
            rule_id="code_domain",
            kind=RuleKind.DOMAIN,
            columns=("code",),
            allowed_values=("A1", "B2"),
        ),
        QualityRule(
            rule_id="amount_integer",
            kind=RuleKind.TYPE,
            columns=("amount",),
            expected_type="integer",
        ),
        QualityRule(
            rule_id="start_before_end",
            kind=RuleKind.COMPARE,
            columns=("start", "end"),
            operator="le",
        ),
        QualityRule(
            rule_id="unique_key",
            kind=RuleKind.UNIQUE_KEY,
            columns=("key",),
        ),
        QualityRule(
            rule_id="code_required",
            kind=RuleKind.REQUIRED,
            columns=("code",),
        ),
    )

    report = _profile(first, second, request=_request(rules=rules))

    assert _metric(report, "validity.regex", "code_pattern").numerator == 3
    assert _metric(report, "validity.regex", "code_pattern").denominator == 4
    assert _metric(report, "validity.range", "amount_range").status is MetricStatus.PASSED
    assert _metric(report, "validity.domain", "code_domain").numerator == 3
    assert _metric(report, "validity.type", "amount_integer").value == 1.0
    assert _metric(report, "consistency.compare", "start_before_end").value == 0.75
    assert _metric(report, "uniqueness.unique_key", "unique_key").numerator == 3
    assert _metric(report, "uniqueness.unique_key", "unique_key").denominator == 4
    assert _metric(report, "completeness.required", "code_required").value == 1.0
    assert _metric(report, "consistency.compare", "start_before_end").scope is MetricScope.RULE


def test_rule_type_date_and_domain_edge_cases() -> None:
    frame = pd.DataFrame(
        {
            "when": ["2026-01-01", "not-a-date", ""],
            "value": ["1", "2", None],
        }
    )
    rules = (
        QualityRule(
            rule_id="date_type",
            kind=RuleKind.TYPE,
            columns=("when",),
            expected_type="date",
        ),
        QualityRule(
            rule_id="string_type",
            kind=RuleKind.TYPE,
            columns=("value",),
            expected_type="string",
        ),
    )

    report = _profile(frame, request=_request(rules=rules))

    assert _metric(report, "validity.type", "date_type").numerator == 1
    assert _metric(report, "validity.type", "date_type").denominator == 2
    assert _metric(report, "validity.type", "string_type").numerator == 2
    assert _metric(report, "validity.type", "string_type").denominator == 2


def test_unhashable_values_fall_back_to_canonical_row_hashes() -> None:
    frame = pd.DataFrame({"payload": [{"a": 1}, {"a": 1}, {"b": [2, 3]}]})

    report = _profile(frame, request=_request())

    assert _metric(report, "duplicate_rows").numerator == 2
    assert _metric(report, "duplicate_rows").denominator == 3
    assert report.columns[0].distinct_count == 2


def test_mixed_mapping_keys_are_safe() -> None:
    frame = pd.DataFrame({"payload": [{"a": 1}, {1: 2}]})

    report = _profile(frame, request=_request())

    assert report.row_count == 2
    assert report.columns[0].distinct_count == 2


def test_empty_source_and_all_null_column() -> None:
    request = _request()
    empty_report = PandasChunkProfiler().merge([], request=request)
    null_frame = pd.DataFrame({"only": [None, None]})
    null_report = _profile(null_frame, request=request)

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

    report = _profile(frame, request=_request())

    assert report.row_count == 0
    assert report.columns[0].name == "id"
    assert report.columns[0].numeric is not None
    assert report.columns[0].numeric.count == 0
    assert _metric(report, "column_completeness", "id").status is MetricStatus.NOT_APPLICABLE


def test_duplicate_missing_and_invalid_chunk_records_are_rejected() -> None:
    request = _request()
    profiler = PandasChunkProfiler()
    record = profiler.profile_chunk(
        pd.DataFrame({"id": [1]}),
        chunk_index=0,
        request=request,
    )

    with pytest.raises(ProfilingError) as duplicate:
        profiler.merge([record, replace(record)], request=request)
    with pytest.raises(ProfilingError) as missing:
        profiler.merge([replace(record, chunk_index=1)], request=request)
    with pytest.raises(ProfilingError) as invalid:
        profiler.merge([object()], request=request)  # type: ignore[list-item]

    assert duplicate.value.code == "PROFILE_CHUNK_SEQUENCE_INVALID"
    assert missing.value.code == "PROFILE_CHUNK_SEQUENCE_INVALID"
    assert invalid.value.code == "PROFILE_CHUNK_INVALID"


def test_schema_drift_and_rule_state_mismatch_are_rejected() -> None:
    request = _request()
    other_request = _request(
        rules=(
            QualityRule(
                rule_id="id_required",
                kind=RuleKind.REQUIRED,
                columns=("id",),
            ),
        )
    )
    profiler = PandasChunkProfiler()
    first = profiler.profile_chunk(
        pd.DataFrame({"id": [1]}),
        chunk_index=0,
        request=request,
    )
    other_schema = profiler.profile_chunk(
        pd.DataFrame({"other": [1]}),
        chunk_index=1,
        request=request,
    )
    other_rules = profiler.profile_chunk(
        pd.DataFrame({"id": [1]}),
        chunk_index=1,
        request=other_request,
    )

    with pytest.raises(ProfilingError) as schema:
        profiler.merge([first, other_schema], request=request)
    with pytest.raises(ProfilingError) as rules:
        profiler.merge([first, other_rules], request=request)

    assert schema.value.code == "PROFILE_SCHEMA_DRIFT"
    assert rules.value.code == "PROFILE_RULE_STATE_MISMATCH"


def test_compatible_numeric_and_all_null_dtype_drift_is_merged() -> None:
    first = pd.DataFrame({"amount": [1, 2], "note": ["ok", "fine"]})
    second = pd.DataFrame({"amount": [3.5, 4.5], "note": [None, None]})

    report = _profile(first, second, request=_request())

    amount, note = report.columns
    assert amount.numeric is not None
    assert amount.numeric.count == 4
    assert amount.dtype == "float64|int64"
    assert note.categorical is not None
    assert note.null_count == 2
    assert note.distinct_count == 2


def test_incompatible_inferred_types_are_rejected() -> None:
    profiler = PandasChunkProfiler()
    request = _request()
    first = profiler.profile_chunk(
        pd.DataFrame({"value": ["a"]}),
        chunk_index=0,
        request=request,
    )
    second = profiler.profile_chunk(
        pd.DataFrame({"value": [1]}),
        chunk_index=1,
        request=request,
    )
    naive = profiler.profile_chunk(
        pd.DataFrame({"value": pd.to_datetime(["2026-01-01"])}),
        chunk_index=0,
        request=request,
    )
    aware = profiler.profile_chunk(
        pd.DataFrame({"value": pd.to_datetime(["2026-01-02"], utc=True)}),
        chunk_index=1,
        request=request,
    )

    with pytest.raises(ProfilingError) as caught:
        profiler.merge([first, second], request=request)
    with pytest.raises(ProfilingError) as dates:
        profiler.merge([naive, aware], request=request)

    assert caught.value.code == "PROFILE_SCHEMA_DRIFT"
    assert caught.value.context["column"] == "value"
    assert dates.value.code == "PROFILE_SCHEMA_DRIFT"
    assert dates.value.context["column"] == "value"


def test_invalid_chunk_and_rule_columns_are_rejected() -> None:
    profiler = PandasChunkProfiler()
    request = _request(
        rules=(
            QualityRule(
                rule_id="missing",
                kind=RuleKind.REQUIRED,
                columns=("missing",),
            ),
        )
    )

    with pytest.raises(ProfilingError) as invalid_chunk:
        profiler.profile_chunk([1, 2], chunk_index=0, request=_request())
    with pytest.raises(ProfilingError) as invalid_index:
        profiler.profile_chunk(
            pd.DataFrame({"id": [1]}),
            chunk_index=-1,
            request=_request(),
        )
    with pytest.raises(ProfilingError) as missing_column:
        profiler.profile_chunk(
            pd.DataFrame({"id": [1]}),
            chunk_index=0,
            request=request,
        )

    assert invalid_chunk.value.code == "PROFILE_INVALID_CHUNK"
    assert invalid_index.value.code == "PROFILE_CHUNK_INDEX_INVALID"
    assert missing_column.value.code == "PROFILE_RULE_COLUMN_NOT_FOUND"


def test_invalid_regex_rule_is_rejected() -> None:
    request = _request(
        rules=(
            QualityRule(
                rule_id="bad_pattern",
                kind=RuleKind.REGEX,
                columns=("code",),
                pattern="[",
            ),
        )
    )

    with pytest.raises(ProfilingError) as caught:
        PandasChunkProfiler().profile_chunk(
            pd.DataFrame({"code": ["a"]}),
            chunk_index=0,
            request=request,
        )

    assert caught.value.code == "PROFILE_RULE_INVALID"


def test_column_failure_is_isolated_as_a_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = profiler_module._profile_column

    def fail_bad_column(
        series: pd.Series,
        *,
        name: str,
        limit: int,
    ) -> object:
        if name == "bad":
            raise RuntimeError("boom")
        return original(series, name=name, limit=limit)

    monkeypatch.setattr(profiler_module, "_profile_column", fail_bad_column)
    request = _request()
    profiler = PandasChunkProfiler()
    record = profiler.profile_chunk(
        pd.DataFrame({"good": [1], "bad": [2]}),
        chunk_index=0,
        request=request,
    )
    report = profiler.merge([record], request=request)

    assert [column.name for column in report.columns] == ["good"]
    assert report.warnings[0].code == "PROFILE_COLUMN_FAILED"
    assert report.warnings[0].column == "bad"
    assert report.warnings[0].details["error_type"] == "RuntimeError"


def test_column_failure_in_one_chunk_does_not_break_merge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = profiler_module._profile_column

    def fail_first_bad_chunk(
        series: pd.Series,
        *,
        name: str,
        limit: int,
    ) -> object:
        if name == "bad" and series.tolist() == [2]:
            raise RuntimeError("boom")
        return original(series, name=name, limit=limit)

    monkeypatch.setattr(profiler_module, "_profile_column", fail_first_bad_chunk)
    request = _request()
    profiler = PandasChunkProfiler()
    first = profiler.profile_chunk(
        pd.DataFrame({"good": [1], "bad": [2]}),
        chunk_index=0,
        request=request,
    )
    second = profiler.profile_chunk(
        pd.DataFrame({"good": [2], "bad": [3]}),
        chunk_index=1,
        request=request,
    )
    report = profiler.merge([first, second], request=request)

    assert [column.name for column in report.columns] == ["good"]
    assert report.approximate is True
    assert [warning.code for warning in report.warnings] == ["PROFILE_COLUMN_FAILED"]


def test_sample_scope_requires_approximate_and_duplicate_columns_are_rejected() -> None:
    frame = pd.DataFrame([[1, 2]], columns=["x", "x"])

    with pytest.raises(ValueError, match="approximate"):
        _request(scope=ProfileScope.SAMPLE)
    with pytest.raises(ProfilingError) as caught:
        PandasChunkProfiler().profile_chunk(
            frame,
            chunk_index=0,
            request=_request(),
        )

    assert caught.value.code == "PROFILE_DUPLICATE_COLUMN_NAME"


def test_successful_sample_report_is_approximate() -> None:
    request = _request(scope=ProfileScope.SAMPLE, approximate=True)

    report = _profile(pd.DataFrame({"id": [1, 2]}), request=request)

    assert report.scope is ProfileScope.SAMPLE
    assert report.approximate is True
