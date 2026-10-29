"""Pandas profiling with mergeable per-chunk state."""

from __future__ import annotations

import hashlib
import heapq
import json
import math
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import replace
from typing import Any, Final, cast

import pandas as pd

from application.profiling.definitions import (
    ACCURACY_FORMULA,
    COLUMN_COMPLETENESS_FORMULA,
    COLUMN_UNIQUENESS_FORMULA,
    DATASET_COMPLETENESS_FORMULA,
    DUPLICATE_ROWS_FORMULA,
    NO_RULES_FORMULA,
    ROW_COMPLETENESS_FORMULA,
    rule_formula,
    rule_metric_name,
)
from application.profiling.models import ProfileRequest
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
    QualityRule,
    RuleChunkState,
    RuleKind,
    ValueCount,
)
from domain.errors import ProfilingError, SandboxError
from infrastructure.profiling.spill import NumericSpillPort

_MAX_LABEL_LENGTH: Final[int] = 500


class PandasChunkProfiler:
    """Profiles DataFrame chunks and merges only mergeable state."""

    def __init__(self, spill: NumericSpillPort | None = None) -> None:
        self._spill = spill

    def profile_chunk(
        self,
        chunk: object,
        *,
        chunk_index: int,
        request: ProfileRequest,
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
        _require_rule_columns(chunk, request.rules)
        rules = tuple(_evaluate_rules(chunk, request.rules, request))

        row_count = len(chunk)
        missing_rows = [False] * row_count
        columns: list[ChunkColumnState] = []
        warnings: list[ProfileWarning] = []
        for column in chunk.columns:
            name = str(column)
            try:
                state, column_missing = _profile_column(
                    chunk[column],
                    name=name,
                    limit=request.limits.max_distinct_values,
                )
            except SandboxError:
                raise
            except Exception as exc:
                warnings.append(
                    ProfileWarning(
                        code="PROFILE_COLUMN_FAILED",
                        message="Column profiling failed",
                        column=name,
                        details={"error_type": type(exc).__name__},
                    )
                )
                columns.append(
                    ChunkColumnState(
                        name=name,
                        dtype=str(chunk[column].dtype),
                        row_count=row_count,
                        null_count=0,
                        empty_count=0,
                        failed=True,
                    )
                )
                for index in range(row_count):
                    missing_rows[index] = True
                continue
            if self._spill is not None and state.numeric is not None:
                numbers = state.numeric.values
                if numbers:
                    reference = self._spill.write(
                        request,
                        chunk_index=chunk_index,
                        column=name,
                        values=numbers,
                    )
                    state = replace(
                        state,
                        numeric=replace(
                            state.numeric,
                            values=(),
                            values_ref=reference,
                        ),
                    )
            columns.append(state)
            for index, missing in enumerate(column_missing):
                if missing:
                    missing_rows[index] = True

        row_hashes, row_hashes_capped = _row_fingerprints(
            chunk,
            limit=request.limits.max_row_hashes,
        )
        return ChunkProfile(
            chunk_index=chunk_index,
            row_count=row_count,
            complete_rows=row_count - sum(missing_rows),
            columns=tuple(columns),
            row_hashes=row_hashes,
            row_hashes_capped=row_hashes_capped,
            rules=rules,
            warnings=tuple(warnings),
        )

    def merge(
        self,
        chunks: Sequence[ChunkProfile],
        *,
        request: ProfileRequest,
    ) -> ProfileReport:
        ordered = _validated_chunk_order(chunks)
        _require_same_schema(ordered)
        _require_same_rules(ordered)

        row_count = sum(chunk.row_count for chunk in ordered)
        complete_rows = sum(chunk.complete_rows for chunk in ordered)
        columns = _merge_columns(ordered, request, self._spill)
        metrics = _build_metrics(
            columns=columns,
            row_count=row_count,
            complete_rows=complete_rows,
            chunks=ordered,
            request=request,
        )
        warnings = [warning for chunk in ordered for warning in chunk.warnings] + _cap_warnings(
            columns, ordered, request
        )
        approximate = (
            request.approximate
            or any(column.numeric is not None and column.numeric.approximate for column in columns)
            or any(metric.approximate for metric in metrics)
            or any(warning.code == "PROFILE_COLUMN_FAILED" for warning in warnings)
        )
        schema_hash = request.schema_hash or _schema_hash(columns)

        return ProfileReport(
            run_id=request.run_id,
            source_id=request.source_id,
            source_type=request.source_type,
            row_count=row_count,
            chunk_count=len(ordered),
            chunk_size=request.chunk_size,
            scope=request.scope,
            method=request.method,
            merge_method=request.merge_method,
            approximate=approximate,
            columns=columns,
            metrics=metrics,
            warnings=tuple(warnings),
            content_hash=request.content_hash,
            schema_hash=schema_hash,
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
    if column.failed:
        return None
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


def _require_same_rules(chunks: Sequence[ChunkProfile]) -> None:
    if not chunks:
        return
    expected = tuple(rule.rule_id for rule in chunks[0].rules)
    for chunk in chunks[1:]:
        actual = tuple(rule.rule_id for rule in chunk.rules)
        if actual != expected:
            raise ProfilingError(
                code="PROFILE_RULE_STATE_MISMATCH",
                message="Profiled chunks do not share the same rule records",
                module=__name__,
                context={"chunk_index": chunk.chunk_index},
            )


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
    request: ProfileRequest,
    spill: NumericSpillPort | None,
) -> tuple[ColumnStatistics, ...]:
    if not chunks:
        return ()
    names = [column.name for column in chunks[0].columns]
    merged: list[ColumnStatistics] = []
    for name in names:
        states = [_column_state(chunk, name) for chunk in chunks]
        if any(state.failed for state in states):
            continue
        merged.append(
            _merge_column(
                states,
                max_frequency_rows=request.limits.max_frequency_rows,
                max_distinct_values=request.limits.max_distinct_values,
                spill=spill,
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
    max_distinct_values: int,
    spill: NumericSpillPort | None,
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
                if len(frequency) >= max_distinct_values:
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
        numeric = _merge_numeric(
            states,
            spill=spill,
            max_distinct_values=max_distinct_values,
        )
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
    spill: NumericSpillPort | None,
    max_distinct_values: int,
) -> NumericStatistics | None:
    numeric_states = [state.numeric for state in states if state.numeric is not None]
    if not numeric_states:
        return None
    count = sum(numeric.count for numeric in numeric_states)
    non_finite_count = sum(numeric.non_finite_count for numeric in numeric_states)
    total = math.fsum(numeric.total for numeric in numeric_states)
    minimum = min(
        (numeric.minimum for numeric in numeric_states if numeric.minimum is not None),
        default=None,
    )
    maximum = max(
        (numeric.maximum for numeric in numeric_states if numeric.maximum is not None),
        default=None,
    )
    if count == 0:
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

    in_memory: list[float] = []
    refs: list[str] = []
    for numeric in numeric_states:
        if numeric.values:
            in_memory.extend(numeric.values)
        elif numeric.values_ref is not None:
            refs.append(numeric.values_ref)
    if refs and spill is None:
        raise ProfilingError(
            code="PROFILE_SPILL_UNAVAILABLE",
            message="Spilled numeric values cannot be read by this profiler",
            module=__name__,
            context={"spill_references": len(refs)},
        )

    iterators: list[Iterable[float]] = []
    if in_memory:
        in_memory.sort()
        iterators.append(in_memory)
    if spill is not None:
        iterators.extend(spill.iter_values(reference) for reference in refs)
    stream = heapq.merge(*iterators)

    middle = count // 2
    targets = {middle} if count % 2 else {middle - 1, middle}
    medians: dict[int, float] = {}
    frequency: dict[float, int] = {}
    mode_capped = False
    streamed = 0
    for index, value in enumerate(stream):
        if index in targets:
            medians[index] = value
        existing = frequency.get(value)
        if existing is not None:
            frequency[value] = existing + 1
        elif len(frequency) < max_distinct_values:
            frequency[value] = 1
        else:
            mode_capped = True
        streamed += 1

    if streamed != count:
        raise ProfilingError(
            code="PROFILE_SPILL_COUNT_MISMATCH",
            message="Spilled numeric values do not match their recorded count",
            module=__name__,
            context={"expected": count, "actual": streamed},
        )
    median = medians[middle] if count % 2 else (medians[middle - 1] + medians[middle]) / 2.0
    mode: tuple[float, ...] = ()
    if not mode_capped and frequency:
        top = max(frequency.values())
        mode = tuple(sorted(value for value, item_count in frequency.items() if item_count == top))
    return NumericStatistics(
        count=count,
        total=total,
        minimum=minimum,
        maximum=maximum,
        mean=total / count,
        median=median,
        mode=mode,
        non_finite_count=non_finite_count,
        approximate=mode_capped,
    )


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
    for state in states:
        if state.dates is None:
            continue
        count += state.dates.count
        if state.dates.count == 0:
            continue
        timezone = timezone or state.dates.timezone
        if minimum_epoch is None or (
            state.dates.minimum_epoch is not None and state.dates.minimum_epoch < minimum_epoch
        ):
            minimum_epoch = state.dates.minimum_epoch
            minimum = state.dates.minimum
        if maximum_epoch is None or (
            state.dates.maximum_epoch is not None and state.dates.maximum_epoch > maximum_epoch
        ):
            maximum_epoch = state.dates.maximum_epoch
            maximum = state.dates.maximum
    range_seconds = None
    if minimum_epoch is not None and maximum_epoch is not None:
        range_seconds = maximum_epoch - minimum_epoch
    return DateTimeStatistics(
        count=count,
        minimum=minimum,
        maximum=maximum,
        range_seconds=range_seconds,
        range_iso=_iso_duration(range_seconds),
        timezone=timezone,
    )


def _iso_duration(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    total = max(round(seconds), 0)
    days, remainder = divmod(total, 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minutes, secs = divmod(remainder, 60)
    date_part = f"P{days}D" if days else "P"
    time_part = ""
    if hours or minutes or secs:
        time_part = f"T{hours}H{minutes}M{secs}S"
    if not date_part.endswith("D"):
        if time_part:
            return f"{date_part}{time_part}"
        return "PT0S"
    return f"{date_part}{time_part}"


def _build_metrics(
    *,
    columns: Sequence[ColumnStatistics],
    row_count: int,
    complete_rows: int,
    chunks: Sequence[ChunkProfile],
    request: ProfileRequest,
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
                threshold=request.thresholds.completeness,
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
            threshold=request.thresholds.completeness,
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
            threshold=request.thresholds.completeness,
            formula=DATASET_COMPLETENESS_FORMULA,
            details={"total_cells": total_cells},
        )
    )

    row_hashes: list[str] = []
    row_hashes_capped = any(chunk.row_hashes_capped for chunk in chunks)
    for chunk in chunks:
        remaining = request.limits.max_row_hashes - len(row_hashes)
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
            threshold=request.thresholds.uniqueness,
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
                threshold=request.thresholds.uniqueness,
                formula=COLUMN_UNIQUENESS_FORMULA,
                approximate=column.distinct_capped,
                details={"capped": column.distinct_capped},
            )
        )

    rule_states = _merge_rule_states(chunks, request)
    metrics.extend(
        _rule_metrics(
            request.rules,
            rule_states,
            request=request,
        )
    )
    if not any(rule.family is MetricFamily.CONSISTENCY for rule in request.rules):
        metrics.append(_not_applicable_metric(MetricFamily.CONSISTENCY, request))
    if not any(rule.family is MetricFamily.VALIDITY for rule in request.rules):
        metrics.append(_not_applicable_metric(MetricFamily.VALIDITY, request))
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


def _merge_rule_states(
    chunks: Sequence[ChunkProfile],
    request: ProfileRequest,
) -> dict[str, RuleChunkState]:
    merged: dict[str, RuleChunkState] = {}
    for rule in request.rules:
        states = [_rule_state(chunk, rule.rule_id) for chunk in chunks]
        if rule.kind is RuleKind.UNIQUE_KEY:
            hashes: list[str] = []
            capped = False
            denominator = 0
            for state in states:
                denominator += state.denominator
                hashes.extend(state.key_hashes)
                capped = capped or state.key_hashes_capped
            if len(hashes) > request.limits.max_row_hashes:
                hashes = hashes[: request.limits.max_row_hashes]
                capped = True
            merged[rule.rule_id] = RuleChunkState(
                rule_id=rule.rule_id,
                numerator=len(set(hashes)),
                denominator=denominator,
                key_hashes=tuple(hashes),
                key_hashes_capped=capped,
            )
        else:
            merged[rule.rule_id] = RuleChunkState(
                rule_id=rule.rule_id,
                numerator=sum(state.numerator for state in states),
                denominator=sum(state.denominator for state in states),
            )
    return merged


def _rule_state(chunk: ChunkProfile, rule_id: str) -> RuleChunkState:
    for state in chunk.rules:
        if state.rule_id == rule_id:
            return state
    raise ProfilingError(
        code="PROFILE_RULE_STATE_MISSING",
        message="A chunk is missing a declared rule record",
        module=__name__,
        context={"chunk_index": chunk.chunk_index, "rule_id": rule_id},
    )


def _rule_metrics(
    rules: Sequence[QualityRule],
    states: Mapping[str, RuleChunkState],
    *,
    request: ProfileRequest,
) -> list[MetricResult]:
    metrics: list[MetricResult] = []
    for rule in rules:
        state = states[rule.rule_id]
        approximate = state.key_hashes_capped
        metrics.append(
            _ratio_metric(
                metric=rule_metric_name(rule),
                family=rule.family,
                scope=MetricScope.RULE,
                subject=rule.rule_id,
                numerator=state.numerator,
                denominator=state.denominator,
                threshold=request.rule_threshold(rule),
                formula=rule_formula(rule),
                approximate=approximate,
                details={
                    "kind": rule.kind.value,
                    "columns": list(rule.columns),
                    "capped": approximate,
                    **(
                        {"duplicate_key_rows": max(state.denominator - state.numerator, 0)}
                        if rule.kind is RuleKind.UNIQUE_KEY
                        else {}
                    ),
                },
            )
        )
    return metrics


def _ratio_metric(
    *,
    metric: str,
    family: MetricFamily,
    scope: MetricScope,
    subject: str,
    numerator: int,
    denominator: int,
    threshold: float | None,
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
        threshold=threshold,
        status=_metric_status(value, threshold, approximate),
        formula=formula,
        details=details or {},
        approximate=approximate,
    )


def _metric_status(
    value: float | None,
    threshold: float | None,
    approximate: bool,
) -> MetricStatus:
    if value is None:
        return MetricStatus.NOT_APPLICABLE
    if threshold is not None and value < threshold:
        return MetricStatus.FAIL
    if approximate:
        return MetricStatus.WARN
    return MetricStatus.PASSED


def _not_applicable_metric(
    family: MetricFamily,
    request: ProfileRequest,
) -> MetricResult:
    return MetricResult(
        metric=f"{family.value}.rules",
        family=family,
        scope=MetricScope.DATASET,
        subject="*",
        numerator=None,
        denominator=None,
        value=None,
        threshold=request.thresholds.for_family(family),
        status=MetricStatus.NOT_APPLICABLE,
        formula=NO_RULES_FORMULA,
        details={"rules_declared": 0},
    )


def _cap_warnings(
    columns: Sequence[ColumnStatistics],
    chunks: Sequence[ChunkProfile],
    request: ProfileRequest,
) -> list[ProfileWarning]:
    warnings: list[ProfileWarning] = []
    for column in columns:
        if column.distinct_capped:
            warnings.append(
                ProfileWarning(
                    code="PROFILE_DISTINCT_CAPPED",
                    message="Distinct-value tracking reached its configured limit",
                    column=column.name,
                    details={"limit": request.limits.max_distinct_values},
                )
            )
        if column.numeric is not None and column.numeric.approximate:
            warnings.append(
                ProfileWarning(
                    code="PROFILE_NUMERIC_MODE_CAPPED",
                    message="Numeric mode tracking reached its configured limit",
                    column=column.name,
                    details={"limit": request.limits.max_distinct_values},
                )
            )
        if column.categorical is not None and column.categorical.truncated:
            warnings.append(
                ProfileWarning(
                    code="PROFILE_FREQUENCY_TABLE_TRUNCATED",
                    message="Categorical frequency output was truncated",
                    column=column.name,
                    details={"limit": request.limits.max_frequency_rows},
                )
            )
    row_hash_count = sum(len(chunk.row_hashes) for chunk in chunks)
    if any(chunk.row_hashes_capped for chunk in chunks) or (
        row_hash_count > request.limits.max_row_hashes
    ):
        warnings.append(
            ProfileWarning(
                code="PROFILE_ROW_HASHES_CAPPED",
                message="Row fingerprint tracking reached its configured limit",
                details={"limit": request.limits.max_row_hashes},
            )
        )
    for rule in request.rules:
        if rule.kind is not RuleKind.UNIQUE_KEY:
            continue
        states = [
            state for chunk in chunks for state in chunk.rules if state.rule_id == rule.rule_id
        ]
        capped = any(state.key_hashes_capped for state in states) or (
            sum(len(state.key_hashes) for state in states) > request.limits.max_row_hashes
        )
        if capped:
            warnings.append(
                ProfileWarning(
                    code="PROFILE_KEY_HASHES_CAPPED",
                    message="Key fingerprint tracking reached its configured limit",
                    rule_id=rule.rule_id,
                    details={"limit": request.limits.max_row_hashes},
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


def _require_rule_columns(
    frame: pd.DataFrame,
    rules: Sequence[QualityRule],
) -> None:
    for rule in rules:
        missing = [column for column in rule.columns if column not in frame.columns]
        if missing:
            raise ProfilingError(
                code="PROFILE_RULE_COLUMN_NOT_FOUND",
                message="A declared rule references missing columns",
                module=__name__,
                context={"rule_id": rule.rule_id, "missing_columns": missing},
            )


def _evaluate_rules(
    frame: pd.DataFrame,
    rules: Sequence[QualityRule],
    request: ProfileRequest,
) -> list[RuleChunkState]:
    return [_evaluate_rule(frame, rule, limit=request.limits.max_row_hashes) for rule in rules]


def _evaluate_rule(
    frame: pd.DataFrame,
    rule: QualityRule,
    *,
    limit: int,
) -> RuleChunkState:
    if rule.kind is RuleKind.REQUIRED:
        series = frame[rule.columns[0]]
        present = sum(
            1 for value in series.tolist() if not _is_null(value) and not _is_empty(value)
        )
        return RuleChunkState(
            rule_id=rule.rule_id,
            numerator=present,
            denominator=len(series),
        )
    if rule.kind is RuleKind.UNIQUE_KEY:
        complete = _complete_rows(frame[list(rule.columns)])
        hashes, capped = _row_fingerprints(complete, limit=limit)
        return RuleChunkState(
            rule_id=rule.rule_id,
            numerator=len(set(hashes)),
            denominator=len(complete),
            key_hashes=hashes,
            key_hashes_capped=capped,
        )
    if rule.kind is RuleKind.REGEX:
        try:
            pattern = re.compile(rule.pattern or "")
        except re.error as exc:
            raise ProfilingError(
                code="PROFILE_RULE_INVALID",
                message="A declared regex rule is invalid",
                module=__name__,
                context={"rule_id": rule.rule_id, "error_type": type(exc).__name__},
            ) from exc
        return _count_values(
            frame[rule.columns[0]],
            rule.rule_id,
            lambda value: pattern.fullmatch(str(value)) is not None,
        )
    if rule.kind is RuleKind.RANGE:
        return _count_values(
            frame[rule.columns[0]],
            rule.rule_id,
            lambda value: _matches_range(value, rule.minimum, rule.maximum),
        )
    if rule.kind is RuleKind.DOMAIN:
        allowed = frozenset(rule.allowed_values)
        return _count_values(
            frame[rule.columns[0]],
            rule.rule_id,
            lambda value: _value_label(value) in allowed,
        )
    if rule.kind is RuleKind.TYPE:
        expected = rule.expected_type or ""
        return _count_values(
            frame[rule.columns[0]],
            rule.rule_id,
            lambda value: _matches_type(value, expected),
        )
    return _compare_rule(frame, rule)


def _count_values(
    series: pd.Series,
    rule_id: str,
    predicate: Callable[[object], bool],
) -> RuleChunkState:
    numerator = 0
    denominator = 0
    for value in series.tolist():
        if _is_null(value) or _is_empty(value):
            continue
        denominator += 1
        if predicate(value):
            numerator += 1
    return RuleChunkState(
        rule_id=rule_id,
        numerator=numerator,
        denominator=denominator,
    )


def _compare_rule(frame: pd.DataFrame, rule: QualityRule) -> RuleChunkState:
    left_values = frame[rule.columns[0]].tolist()
    right_values = frame[rule.columns[1]].tolist()
    numerator = 0
    denominator = 0
    operator = rule.operator or ""
    for left, right in zip(left_values, right_values, strict=True):
        if _is_null(left) or _is_null(right) or _is_empty(left) or _is_empty(right):
            continue
        denominator += 1
        if operator in {"eq", "ne"}:
            equal = _value_canonical(left) == _value_canonical(right)
            valid = equal if operator == "eq" else not equal
        else:
            try:
                if operator == "lt":
                    valid = left < right
                elif operator == "le":
                    valid = left <= right
                elif operator == "gt":
                    valid = left > right
                else:
                    valid = left >= right
            except (TypeError, ValueError):
                valid = False
        if valid:
            numerator += 1
    return RuleChunkState(
        rule_id=rule.rule_id,
        numerator=numerator,
        denominator=denominator,
    )


def _matches_range(value: object, minimum: float | None, maximum: float | None) -> bool:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    if not math.isfinite(number):
        return False
    if minimum is not None and number < minimum:
        return False
    return maximum is None or number <= maximum


def _matches_type(value: object, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        if isinstance(value, bool):
            return False
        try:
            return float(value).is_integer()  # type: ignore[arg-type]
        except (TypeError, ValueError, OverflowError):
            return False
    if expected == "number":
        try:
            return math.isfinite(float(value))  # type: ignore[arg-type]
        except (TypeError, ValueError, OverflowError):
            return False
    if expected == "date":
        try:
            return not pd.isna(pd.Timestamp(cast(Any, value)))
        except (TypeError, ValueError, OverflowError):
            return False
    return False


def _complete_rows(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    complete = [
        not any(_is_null(value) or _is_empty(value) for value in row)
        for row in frame.itertuples(index=False, name=None)
    ]
    return frame.loc[complete]


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
