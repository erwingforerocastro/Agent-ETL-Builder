"""Pandas profiling with mergeable per-chunk state."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final, cast

import pandas as pd

from application.profiling.definitions import (
    ACCURACY_FORMULA,
    COLUMN_COMPLETENESS_FORMULA,
    COLUMN_UNIQUENESS_FORMULA,
    DATASET_COMPLETENESS_FORMULA,
    DEFAULT_QUALITY_THRESHOLD,
    DUPLICATE_ROWS_FORMULA,
    NO_RULES_FORMULA,
    ROW_COMPLETENESS_FORMULA,
)
from application.profiling.models import ProfileLimits, ProfileRequest
from domain.entities.profiling import (
    CategoricalStatistics,
    ChunkColumnState,
    ChunkDateState,
    ChunkNumericState,
    ChunkProfile,
    ColumnStatistics,
    DateTimeStatistics,
    MetricFamily,
    MetricResult,
    MetricScope,
    MetricStatus,
    NumericStatistics,
    ProfileReport,
    ProfileWarning,
    ValueCount,
)
from domain.errors import ProfilingError, SandboxError

_MAX_LABEL_LENGTH: Final[int] = 500


class PandasChunkProfiler:
    """Profiles DataFrame chunks and merges only mergeable state."""

    def __init__(self, limits: ProfileLimits | None = None) -> None:
        self._limits = limits or ProfileLimits()

    def profile_chunk(
        self,
        chunk: object,
        *,
        chunk_index: int,
    ) -> ChunkProfile:
        if not isinstance(chunk_index, int) or isinstance(chunk_index, bool) or chunk_index < 0:
            raise ProfilingError(
                code="PROFILE_CHUNK_INDEX_INVALID",
                message="Chunk index must be a non-negative integer",
                module=__name__,
                context={"chunk_index": chunk_index},
            )
        if not isinstance(chunk, pd.DataFrame):
            raise ProfilingError(
                code="PROFILE_INVALID_CHUNK",
                message="Profiling chunks must be DataFrames",
                module=__name__,
                context={"chunk_index": chunk_index, "chunk_type": type(chunk).__name__},
            )
        if chunk.columns.duplicated().any():
            raise ProfilingError(
                code="PROFILE_DUPLICATE_COLUMN_NAME",
                message="Profiling requires unique column names",
                module=__name__,
                context={"chunk_index": chunk_index},
            )

        row_count = len(chunk)
        missing_rows = [False] * row_count
        columns: list[ChunkColumnState] = []
        for column in chunk.columns:
            name = str(column)
            try:
                state, column_missing = _profile_column(
                    chunk[column],
                    name=name,
                    limit=self._limits.max_tracked_values,
                )
            except SandboxError:
                raise
            except Exception as exc:
                raise ProfilingError(
                    code="PROFILE_COLUMN_FAILED",
                    message="Column profiling failed",
                    module=__name__,
                    context={
                        "chunk_index": chunk_index,
                        "column": name,
                        "error_type": type(exc).__name__,
                    },
                ) from exc
            columns.append(state)
            for index, missing in enumerate(column_missing):
                if missing:
                    missing_rows[index] = True

        row_hashes, row_hashes_capped = _row_fingerprints(
            chunk,
            limit=self._limits.max_tracked_values,
        )
        return ChunkProfile(
            chunk_index=chunk_index,
            row_count=row_count,
            complete_rows=row_count - sum(missing_rows),
            columns=tuple(columns),
            row_hashes=row_hashes,
            row_hashes_capped=row_hashes_capped,
        )

    def merge(
        self,
        chunks: Sequence[ChunkProfile],
        *,
        request: ProfileRequest,
    ) -> ProfileReport:
        ordered = _validated_chunk_order(chunks)
        _require_same_schema(ordered)

        row_count = sum(chunk.row_count for chunk in ordered)
        complete_rows = sum(chunk.complete_rows for chunk in ordered)
        columns = _merge_columns(ordered, self._limits)
        metrics = _build_metrics(
            columns=columns,
            row_count=row_count,
            complete_rows=complete_rows,
            chunks=ordered,
            limits=self._limits,
        )
        warnings = _cap_warnings(columns, ordered, self._limits)
        approximate = any(
            column.numeric is not None and column.numeric.approximate for column in columns
        ) or any(metric.approximate for metric in metrics)
        return ProfileReport(
            run_id=request.run_id,
            source_id=request.source_id,
            source_type=request.source_type,
            row_count=row_count,
            chunk_count=len(ordered),
            chunk_size=request.chunk_size,
            approximate=approximate,
            columns=columns,
            metrics=metrics,
            warnings=tuple(warnings),
            content_hash=request.content_hash,
            schema_hash=_schema_hash(columns),
        )


def _validated_chunk_order(chunks: Sequence[ChunkProfile]) -> tuple[ChunkProfile, ...]:
    if any(not isinstance(chunk, ChunkProfile) for chunk in chunks):
        raise ProfilingError(
            code="PROFILE_CHUNK_INVALID",
            message="Chunk records must be ChunkProfile values",
            module=__name__,
        )
    ordered = tuple(sorted(chunks, key=lambda chunk: chunk.chunk_index))
    expected = tuple(range(len(ordered)))
    actual = tuple(chunk.chunk_index for chunk in ordered)
    if actual != expected:
        raise ProfilingError(
            code="PROFILE_CHUNK_SEQUENCE_INVALID",
            message="Chunk records must be unique and sequential",
            module=__name__,
            context={"chunk_indexes": list(actual)},
        )
    return ordered


def _require_same_schema(chunks: Sequence[ChunkProfile]) -> None:
    if not chunks:
        return
    expected = chunks[0].columns
    names = [column.name for column in expected]
    for chunk in chunks[1:]:
        if [column.name for column in chunk.columns] != names:
            raise _schema_drift_error(chunk, expected, chunk.columns)
    for index, name in enumerate(names):
        kinds = {
            kind
            for kind in (
                _column_kind(chunk.columns[index])
                for chunk in chunks
                if _present_count(chunk.columns[index]) > 0
            )
            if kind is not None
        }
        if len(kinds) > 1:
            raise ProfilingError(
                code="PROFILE_SCHEMA_DRIFT",
                message="A column has incompatible inferred types across chunks",
                module=__name__,
                context={"column": name, "kinds": sorted(kinds)},
            )


def _column_kind(column: ChunkColumnState) -> str | None:
    if column.numeric is not None:
        return "numeric"
    if column.dates is not None:
        return f"datetime:{column.dates.timezone or 'naive'}"
    if _present_count(column) > 0:
        return "categorical"
    return None


def _schema_drift_error(
    chunk: ChunkProfile,
    expected: Sequence[ChunkColumnState],
    actual: Sequence[ChunkColumnState],
) -> ProfilingError:
    return ProfilingError(
        code="PROFILE_SCHEMA_DRIFT",
        message="Profiled chunks do not share one compatible schema",
        module=__name__,
        context={
            "chunk_index": chunk.chunk_index,
            "expected_columns": [column.name for column in expected],
            "actual_columns": [column.name for column in actual],
        },
    )


def _present_count(column: ChunkColumnState) -> int:
    return column.row_count - column.null_count - column.empty_count


def _profile_column(
    series: pd.Series,
    *,
    name: str,
    limit: int,
) -> tuple[ChunkColumnState, list[bool]]:
    row_count = len(series)
    missing = [False] * row_count
    null_count = 0
    empty_count = 0
    values: list[float] = []
    non_finite_count = 0
    frequency: dict[str, ValueCount] = {}
    values_capped = False
    is_numeric = pd.api.types.is_numeric_dtype(series.dtype) and not pd.api.types.is_bool_dtype(
        series.dtype
    )
    is_datetime = pd.api.types.is_datetime64_any_dtype(series.dtype)
    date_count = 0
    minimum_epoch: float | None = None
    maximum_epoch: float | None = None
    minimum_iso: str | None = None
    maximum_iso: str | None = None
    timezone: str | None = None

    for index, value in enumerate(series.tolist()):
        if _is_null(value):
            null_count += 1
            missing[index] = True
            continue
        if _is_empty(value):
            empty_count += 1
            missing[index] = True
            continue

        canonical = _value_canonical(value)
        existing = frequency.get(canonical)
        if existing is not None:
            frequency[canonical] = ValueCount(
                label=existing.label,
                count=existing.count + 1,
                canonical=existing.canonical,
            )
        elif len(frequency) < limit:
            frequency[canonical] = ValueCount(
                label=_value_label(value),
                count=1,
                canonical=canonical,
            )
        else:
            values_capped = True

        if is_numeric:
            try:
                number = float(value)
            except (TypeError, ValueError):
                non_finite_count += 1
            else:
                if math.isfinite(number):
                    values.append(number)
                else:
                    non_finite_count += 1

        if is_datetime:
            timestamp = pd.Timestamp(value)
            if timestamp.tzinfo is not None:
                timestamp = timestamp.tz_convert("UTC")
                epoch = float(timestamp.timestamp())
                timezone = "UTC"
            else:
                epoch = float(timestamp.value) / 1_000_000_000
            if minimum_epoch is None or epoch < minimum_epoch:
                minimum_epoch = epoch
                minimum_iso = timestamp.isoformat()
            if maximum_epoch is None or epoch > maximum_epoch:
                maximum_epoch = epoch
                maximum_iso = timestamp.isoformat()
            date_count += 1

    numeric = None
    if is_numeric:
        numeric = ChunkNumericState(
            count=len(values),
            total=math.fsum(values),
            minimum=min(values) if values else None,
            maximum=max(values) if values else None,
            values=tuple(values),
            non_finite_count=non_finite_count,
        )

    dates = None
    if is_datetime:
        dates = ChunkDateState(
            count=date_count,
            minimum_epoch=minimum_epoch,
            maximum_epoch=maximum_epoch,
            minimum=minimum_iso,
            maximum=maximum_iso,
            timezone=timezone,
        )

    state = ChunkColumnState(
        name=name,
        dtype=str(series.dtype),
        row_count=row_count,
        null_count=null_count,
        empty_count=empty_count,
        numeric=numeric,
        dates=dates,
        values=tuple(_sorted_value_counts(frequency.values())),
        values_capped=values_capped,
    )
    return state, missing


def _merge_columns(
    chunks: Sequence[ChunkProfile],
    limits: ProfileLimits,
) -> tuple[ColumnStatistics, ...]:
    if not chunks:
        return ()
    names = [column.name for column in chunks[0].columns]
    merged: list[ColumnStatistics] = []
    for name in names:
        states = [_column_state(chunk, name) for chunk in chunks]
        merged.append(
            _merge_column(
                states,
                max_frequency_rows=limits.max_frequency_rows,
                max_tracked_values=limits.max_tracked_values,
            )
        )
    return tuple(merged)


def _column_state(chunk: ChunkProfile, name: str) -> ChunkColumnState:
    for column in chunk.columns:
        if column.name == name:
            return column
    raise ProfilingError(
        code="PROFILE_COLUMN_MISSING",
        message="A chunk is missing a profiled column",
        module=__name__,
        context={"chunk_index": chunk.chunk_index, "column": name},
    )


def _merge_column(
    states: Sequence[ChunkColumnState],
    *,
    max_frequency_rows: int,
    max_tracked_values: int,
) -> ColumnStatistics:
    row_count = sum(state.row_count for state in states)
    null_count = sum(state.null_count for state in states)
    empty_count = sum(state.empty_count for state in states)
    frequency: dict[str, ValueCount] = {}
    capped = any(state.values_capped for state in states)
    for state in states:
        for item in state.values:
            existing = frequency.get(item.canonical)
            if existing is None:
                if len(frequency) >= max_tracked_values:
                    capped = True
                    continue
                frequency[item.canonical] = item
            else:
                frequency[item.canonical] = ValueCount(
                    label=existing.label,
                    count=existing.count + item.count,
                    canonical=existing.canonical,
                )

    dtypes = {state.dtype for state in states}
    mixed_dtypes = len(dtypes) > 1
    numeric_signal = any(
        _present_count(state) > 0 and state.numeric is not None for state in states
    )
    date_signal = any(state.dates is not None and state.dates.count > 0 for state in states)
    non_numeric_signal = any(
        _present_count(state) > 0 and state.numeric is None and state.dates is None
        for state in states
    )
    numeric = None
    if (not mixed_dtypes and states[0].numeric is not None) or (
        mixed_dtypes and numeric_signal and not non_numeric_signal
    ):
        numeric = _merge_numeric(states, max_tracked_values=max_tracked_values)
    dates = None
    if (not mixed_dtypes and states[0].dates is not None) or (
        mixed_dtypes and date_signal and not non_numeric_signal
    ):
        dates = _merge_dates(states)
    categorical = None
    if numeric is None and dates is None:
        all_counts = list(frequency.values())
        if null_count:
            all_counts.append(ValueCount(label="", count=null_count, is_null=True))
        if empty_count:
            all_counts.append(ValueCount(label="", count=empty_count, is_empty=True))
        all_counts.sort(key=lambda item: (-item.count, item.is_null, item.is_empty, item.label))
        truncated = len(all_counts) > max_frequency_rows
        categorical = CategoricalStatistics(
            frequencies=tuple(all_counts[:max_frequency_rows]),
            distinct_count=len(frequency),
            capped=capped,
            truncated=truncated,
        )

    return ColumnStatistics(
        name=states[0].name,
        dtype=states[0].dtype if not mixed_dtypes else "|".join(sorted(dtypes)),
        row_count=row_count,
        null_count=null_count,
        empty_count=empty_count,
        numeric=numeric,
        dates=dates,
        categorical=categorical,
        distinct_count=len(frequency),
        distinct_capped=capped,
    )


def _merge_numeric(
    states: Sequence[ChunkColumnState],
    *,
    max_tracked_values: int,
) -> NumericStatistics | None:
    numeric_states = [state.numeric for state in states if state.numeric is not None]
    if not numeric_states:
        return None
    values: list[float] = []
    non_finite_count = 0
    for numeric in numeric_states:
        values.extend(numeric.values)
        non_finite_count += numeric.non_finite_count
    if not values:
        return NumericStatistics(
            count=0,
            total=0.0,
            minimum=None,
            maximum=None,
            mean=None,
            median=None,
            mode=(),
            non_finite_count=non_finite_count,
        )

    values.sort()
    total = math.fsum(values)
    frequency: dict[float, int] = {}
    mode_capped = False
    for value in values:
        existing = frequency.get(value)
        if existing is not None:
            frequency[value] = existing + 1
        elif len(frequency) < max_tracked_values:
            frequency[value] = 1
        else:
            mode_capped = True
    mode: tuple[float, ...] = ()
    if not mode_capped and frequency:
        top = max(frequency.values())
        mode = tuple(sorted(value for value, count in frequency.items() if count == top))
    return NumericStatistics(
        count=len(values),
        total=total,
        minimum=values[0],
        maximum=values[-1],
        mean=total / len(values),
        median=_median(values),
        mode=mode,
        non_finite_count=non_finite_count,
        approximate=mode_capped,
    )


def _median(values: Sequence[float]) -> float:
    middle = len(values) // 2
    if len(values) % 2:
        return values[middle]
    return (values[middle - 1] + values[middle]) / 2.0


def _merge_dates(states: Sequence[ChunkColumnState]) -> DateTimeStatistics | None:
    date_states = [state.dates for state in states if state.dates is not None]
    if not date_states:
        return None
    count = 0
    minimum_epoch: float | None = None
    maximum_epoch: float | None = None
    minimum: str | None = None
    maximum: str | None = None
    timezone: str | None = None
    for date_state in date_states:
        count += date_state.count
        if date_state.count == 0:
            continue
        timezone = timezone or date_state.timezone
        if minimum_epoch is None or (
            date_state.minimum_epoch is not None and date_state.minimum_epoch < minimum_epoch
        ):
            minimum_epoch = date_state.minimum_epoch
            minimum = date_state.minimum
        if maximum_epoch is None or (
            date_state.maximum_epoch is not None and date_state.maximum_epoch > maximum_epoch
        ):
            maximum_epoch = date_state.maximum_epoch
            maximum = date_state.maximum
    range_seconds = None
    if minimum_epoch is not None and maximum_epoch is not None:
        range_seconds = maximum_epoch - minimum_epoch
    return DateTimeStatistics(
        count=count,
        minimum=minimum,
        maximum=maximum,
        range_seconds=range_seconds,
        timezone=timezone,
    )


def _build_metrics(
    *,
    columns: Sequence[ColumnStatistics],
    row_count: int,
    complete_rows: int,
    chunks: Sequence[ChunkProfile],
    limits: ProfileLimits,
) -> tuple[MetricResult, ...]:
    metrics: list[MetricResult] = []
    for column in columns:
        present = column.present_count
        metrics.append(
            _ratio_metric(
                metric="column_completeness",
                family=MetricFamily.COMPLETENESS,
                scope=MetricScope.COLUMN,
                subject=column.name,
                numerator=present,
                denominator=column.row_count,
                formula=COLUMN_COMPLETENESS_FORMULA,
                details={
                    "null_count": column.null_count,
                    "empty_count": column.empty_count,
                },
            )
        )

    metrics.append(
        _ratio_metric(
            metric="row_completeness",
            family=MetricFamily.COMPLETENESS,
            scope=MetricScope.ROW,
            subject="*",
            numerator=complete_rows,
            denominator=row_count,
            formula=ROW_COMPLETENESS_FORMULA,
            details={"complete_rows": complete_rows, "incomplete_rows": row_count - complete_rows},
        )
    )
    total_cells = row_count * len(columns)
    present_cells = sum(column.present_count for column in columns)
    metrics.append(
        _ratio_metric(
            metric="dataset_completeness",
            family=MetricFamily.COMPLETENESS,
            scope=MetricScope.DATASET,
            subject="*",
            numerator=present_cells,
            denominator=total_cells,
            formula=DATASET_COMPLETENESS_FORMULA,
            details={"total_cells": total_cells},
        )
    )

    row_hashes: list[str] = []
    row_hashes_capped = any(chunk.row_hashes_capped for chunk in chunks)
    for chunk in chunks:
        remaining = limits.max_tracked_values - len(row_hashes)
        if remaining <= 0:
            row_hashes_capped = True
            break
        row_hashes.extend(chunk.row_hashes[:remaining])
        if len(chunk.row_hashes) > remaining:
            row_hashes_capped = True
            break
    distinct_rows = len(set(row_hashes))
    if not row_hashes_capped and len(row_hashes) != row_count:
        row_hashes_capped = True
    metrics.append(
        _ratio_metric(
            metric="duplicate_rows",
            family=MetricFamily.UNIQUENESS,
            scope=MetricScope.DATASET,
            subject="*",
            numerator=distinct_rows,
            denominator=row_count,
            formula=DUPLICATE_ROWS_FORMULA,
            approximate=row_hashes_capped,
            details={
                "duplicate_row_count": max(row_count - distinct_rows, 0),
                "row_hashes_tracked": len(row_hashes),
                "capped": row_hashes_capped,
            },
        )
    )

    for column in columns:
        metrics.append(
            _ratio_metric(
                metric="column_uniqueness",
                family=MetricFamily.UNIQUENESS,
                scope=MetricScope.COLUMN,
                subject=column.name,
                numerator=column.distinct_count,
                denominator=column.present_count,
                formula=COLUMN_UNIQUENESS_FORMULA,
                approximate=column.distinct_capped,
                details={"capped": column.distinct_capped},
            )
        )

    metrics.append(_not_applicable_metric(MetricFamily.CONSISTENCY))
    metrics.append(_not_applicable_metric(MetricFamily.VALIDITY))
    metrics.append(
        MetricResult(
            metric="accuracy",
            family=MetricFamily.ACCURACY,
            scope=MetricScope.DATASET,
            subject="*",
            numerator=None,
            denominator=None,
            value=None,
            threshold=None,
            status=MetricStatus.NOT_APPLICABLE,
            formula=ACCURACY_FORMULA,
            details={"reason": "formula_not_provided"},
        )
    )
    return tuple(metrics)


def _ratio_metric(
    *,
    metric: str,
    family: MetricFamily,
    scope: MetricScope,
    subject: str,
    numerator: int,
    denominator: int,
    formula: str,
    details: Mapping[str, object] | None = None,
    approximate: bool = False,
) -> MetricResult:
    value = numerator / denominator if denominator else None
    return MetricResult(
        metric=metric,
        family=family,
        scope=scope,
        subject=subject,
        numerator=numerator,
        denominator=denominator,
        value=value,
        threshold=DEFAULT_QUALITY_THRESHOLD,
        status=_metric_status(value, approximate),
        formula=formula,
        details=details or {},
        approximate=approximate,
    )


def _metric_status(value: float | None, approximate: bool) -> MetricStatus:
    if value is None:
        return MetricStatus.NOT_APPLICABLE
    if value < DEFAULT_QUALITY_THRESHOLD:
        return MetricStatus.FAIL
    if approximate:
        return MetricStatus.WARN
    return MetricStatus.PASSED


def _not_applicable_metric(family: MetricFamily) -> MetricResult:
    return MetricResult(
        metric=f"{family.value}.rules",
        family=family,
        scope=MetricScope.DATASET,
        subject="*",
        numerator=None,
        denominator=None,
        value=None,
        threshold=DEFAULT_QUALITY_THRESHOLD,
        status=MetricStatus.NOT_APPLICABLE,
        formula=NO_RULES_FORMULA,
        details={"rules_declared": 0},
    )


def _cap_warnings(
    columns: Sequence[ColumnStatistics],
    chunks: Sequence[ChunkProfile],
    limits: ProfileLimits,
) -> list[ProfileWarning]:
    warnings: list[ProfileWarning] = []
    for column in columns:
        if column.distinct_capped:
            warnings.append(
                ProfileWarning(
                    code="PROFILE_DISTINCT_CAPPED",
                    message="Distinct-value tracking reached its configured limit",
                    column=column.name,
                    details={"limit": limits.max_tracked_values},
                )
            )
        if column.numeric is not None and column.numeric.approximate:
            warnings.append(
                ProfileWarning(
                    code="PROFILE_NUMERIC_MODE_CAPPED",
                    message="Numeric mode tracking reached its configured limit",
                    column=column.name,
                    details={"limit": limits.max_tracked_values},
                )
            )
        if column.categorical is not None and column.categorical.truncated:
            warnings.append(
                ProfileWarning(
                    code="PROFILE_FREQUENCY_TABLE_TRUNCATED",
                    message="Categorical frequency output was truncated",
                    column=column.name,
                    details={"limit": limits.max_frequency_rows},
                )
            )
    row_hash_count = sum(len(chunk.row_hashes) for chunk in chunks)
    if any(chunk.row_hashes_capped for chunk in chunks) or (
        row_hash_count > limits.max_tracked_values
    ):
        warnings.append(
            ProfileWarning(
                code="PROFILE_ROW_HASHES_CAPPED",
                message="Row fingerprint tracking reached its configured limit",
                details={"limit": limits.max_tracked_values},
            )
        )
    return warnings


def _schema_hash(columns: Sequence[ColumnStatistics]) -> str | None:
    if not columns:
        return None
    payload = json.dumps(
        [(column.name, column.dtype) for column in columns],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"


def _row_fingerprints(
    frame: pd.DataFrame,
    *,
    limit: int,
) -> tuple[tuple[str, ...], bool]:
    row_count = len(frame)
    if row_count == 0:
        return (), False
    if len(frame.columns) == 0:
        hashes = ("sha256:" + hashlib.sha256(b"[]").hexdigest(),) * row_count
    else:
        try:
            raw = pd.util.hash_pandas_object(frame, index=False, categorize=False)
        except (TypeError, ValueError):
            hashes = tuple(
                _canonical_row_hash(row) for row in frame.itertuples(index=False, name=None)
            )
        else:
            hashes = tuple(f"{int(value):016x}" for value in raw.tolist())
    capped = len(hashes) > limit
    return tuple(hashes[:limit]), capped


def _canonical_row_hash(row: Sequence[object]) -> str:
    payload = json.dumps(
        [_canonical_cell(value) for value in row],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"


def _sorted_value_counts(values: Iterable[ValueCount]) -> list[ValueCount]:
    return sorted(values, key=lambda item: (-item.count, item.label))


def _is_null(value: object) -> bool:
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    if isinstance(value, float):
        return math.isnan(value)
    if isinstance(value, (list, tuple, set, dict)):
        return False
    try:
        result = pd.isna(cast(Any, value))
    except (TypeError, ValueError):
        return False
    return bool(result) if not hasattr(result, "__len__") else False


def _is_empty(value: object) -> bool:
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, bytes):
        return not value.strip()
    return False


def _value_label(value: object) -> str:
    if isinstance(value, str):
        label = value
    elif isinstance(value, bool):
        label = "true" if value else "false"
    elif isinstance(value, int):
        label = str(value)
    elif isinstance(value, float):
        label = _float_label(value)
    elif isinstance(value, Mapping | list | tuple):
        label = _json_text(value)
    elif isinstance(value, set):
        label = _json_text(sorted(value, key=repr))
    elif isinstance(value, bytes):
        label = value.decode("utf-8", errors="backslashreplace")
    else:
        isoformat = getattr(value, "isoformat", None)
        label = isoformat() if callable(isoformat) else str(value)
    if len(label) > _MAX_LABEL_LENGTH:
        return f"{label[: _MAX_LABEL_LENGTH - 3]}..."
    return label


def _value_canonical(value: object) -> str:
    if isinstance(value, str):
        return f"str:{value}"
    if isinstance(value, bool):
        return f"bool:{value}"
    if isinstance(value, int):
        return f"int:{value}"
    if isinstance(value, float):
        return f"number:{_float_label(value)}"
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return f"{type(value).__name__}:{isoformat()}"
    if isinstance(value, bytes):
        return f"bytes:{value.hex()}"
    return f"{type(value).__name__}:{_json_text(value)}"


def _float_label(value: float) -> str:
    if math.isnan(value):
        return "nan"
    if math.isinf(value):
        return "inf" if value > 0 else "-inf"
    return repr(value)


def _json_text(value: object) -> str:
    return json.dumps(
        _json_safe(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _json_safe(value: object) -> object:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, set):
        return [_json_safe(item) for item in sorted(value, key=repr)]
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return isoformat()
    return repr(value)


def _canonical_cell(value: object) -> str:
    if value is None or value is pd.NA or value is pd.NaT:
        return "null"
    if isinstance(value, float):
        if math.isnan(value):
            return "nan"
        if math.isinf(value):
            return "inf" if value > 0 else "-inf"
        return repr(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, Mapping):
        return json.dumps(
            {str(key): _canonical_cell(item) for key, item in value.items()},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    if isinstance(value, list | tuple | set):
        items = value if not isinstance(value, set) else sorted(value, key=repr)
        return json.dumps(
            [_canonical_cell(item) for item in items],
            ensure_ascii=False,
            separators=(",", ":"),
        )
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return json.dumps(isoformat(), ensure_ascii=False)
    return json.dumps(repr(value), ensure_ascii=False)


__all__ = ["PandasChunkProfiler"]
