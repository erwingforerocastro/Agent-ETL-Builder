"""Profiling, quality, and mergeable chunk-state value objects."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from domain.entities._validation import (
    require_non_negative_int,
    require_positive_int,
    require_text,
)
from domain.entities.ingestion import SOURCE_TYPES, SourceType

PROFILE_SCHEMA_VERSION: Final[str] = "1.0.0"
METRIC_DEFINITION_VERSION: Final[str] = "1.0.0"


class MetricFamily(StrEnum):
    """Quality dimensions defined by the profiling contract."""

    COMPLETENESS = "completeness"
    CONSISTENCY = "consistency"
    VALIDITY = "validity"
    UNIQUENESS = "uniqueness"
    ACCURACY = "accuracy"


class MetricScope(StrEnum):
    """What a metric describes."""

    COLUMN = "column"
    ROW = "row"
    DATASET = "dataset"
    RULE = "rule"


class MetricStatus(StrEnum):
    """Outcome after comparing a metric with its threshold."""

    PASSED = "pass"
    FAIL = "fail"
    WARN = "warn"
    NOT_APPLICABLE = "not_applicable"
    ERROR = "error"


class ProfileScope(StrEnum):
    """Whether the profile covered the full source or a bounded sample."""

    FULL = "full"
    SAMPLE = "sample"


class RuleKind(StrEnum):
    """Supported declared quality rules."""

    REQUIRED = "required"
    UNIQUE_KEY = "unique_key"
    REGEX = "regex"
    RANGE = "range"
    DOMAIN = "domain"
    TYPE = "type"
    COMPARE = "compare"


_RULE_TYPES: Final[frozenset[str]] = frozenset({"integer", "number", "date", "string"})
_COMPARE_OPERATORS: Final[frozenset[str]] = frozenset({"eq", "ne", "lt", "le", "gt", "ge"})


def _require_ratio(value: float, field_name: str) -> None:
    if not math.isfinite(value) or value < 0 or value > 1:
        raise ValueError(f"{field_name} must be between 0 and 1")


def _require_finite(value: float, field_name: str) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{field_name} must be finite")


@dataclass(frozen=True, slots=True)
class QualityRule:
    """One explicitly declared consistency, validity, or uniqueness rule."""

    rule_id: str
    kind: RuleKind
    columns: tuple[str, ...]
    threshold: float | None = None
    pattern: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    allowed_values: tuple[str, ...] = ()
    expected_type: str | None = None
    operator: str | None = None

    def __post_init__(self) -> None:
        require_text(self.rule_id, "rule_id")
        if not isinstance(self.kind, RuleKind):
            raise ValueError("kind must be a RuleKind")
        object.__setattr__(self, "columns", tuple(self.columns))
        object.__setattr__(self, "allowed_values", tuple(self.allowed_values))
        if not self.columns:
            raise ValueError("rule columns must not be empty")
        if any(not column.strip() for column in self.columns):
            raise ValueError("rule columns must not be blank")
        if len(set(self.columns)) != len(self.columns):
            raise ValueError("rule columns must be unique")
        if self.threshold is not None:
            _require_ratio(self.threshold, "threshold")
        for value, name in ((self.minimum, "minimum"), (self.maximum, "maximum")):
            if value is not None:
                _require_finite(value, name)
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("minimum must not exceed maximum")
        if any(not item.strip() for item in self.allowed_values):
            raise ValueError("allowed_values must not contain blank values")

        single_column_rules = {
            RuleKind.REQUIRED,
            RuleKind.REGEX,
            RuleKind.RANGE,
            RuleKind.DOMAIN,
            RuleKind.TYPE,
        }
        if self.kind in single_column_rules and len(self.columns) != 1:
            raise ValueError(f"{self.kind.value} rules require exactly one column")
        if self.kind is RuleKind.UNIQUE_KEY and len(self.columns) < 1:
            raise ValueError("unique_key rules require at least one column")
        if self.kind is RuleKind.COMPARE:
            if len(self.columns) != 2:
                raise ValueError("compare rules require exactly two columns")
            if self.operator not in _COMPARE_OPERATORS:
                raise ValueError(f"unsupported compare operator: {self.operator}")
        elif self.operator is not None:
            raise ValueError("operator is only valid for compare rules")
        if self.kind is RuleKind.REGEX:
            if self.pattern is None or not self.pattern.strip():
                raise ValueError("regex rules require a pattern")
        elif self.pattern is not None:
            raise ValueError("pattern is only valid for regex rules")
        if self.kind is RuleKind.RANGE:
            if self.minimum is None and self.maximum is None:
                raise ValueError("range rules require minimum or maximum")
        elif self.minimum is not None or self.maximum is not None:
            raise ValueError("minimum/maximum are only valid for range rules")
        if self.kind is RuleKind.DOMAIN:
            if not self.allowed_values:
                raise ValueError("domain rules require allowed_values")
        elif self.allowed_values:
            raise ValueError("allowed_values are only valid for domain rules")
        if self.kind is RuleKind.TYPE:
            if self.expected_type not in _RULE_TYPES:
                raise ValueError(f"unsupported expected_type: {self.expected_type}")
        elif self.expected_type is not None:
            raise ValueError("expected_type is only valid for type rules")

    @property
    def family(self) -> MetricFamily:
        if self.kind is RuleKind.REQUIRED:
            return MetricFamily.COMPLETENESS
        if self.kind is RuleKind.UNIQUE_KEY:
            return MetricFamily.UNIQUENESS
        if self.kind is RuleKind.COMPARE:
            return MetricFamily.CONSISTENCY
        return MetricFamily.VALIDITY


@dataclass(frozen=True, slots=True)
class MetricResult:
    """One explicit quality metric with its counts and formula."""

    metric: str
    family: MetricFamily
    scope: MetricScope
    subject: str
    numerator: int | None
    denominator: int | None
    value: float | None
    threshold: float | None
    status: MetricStatus
    formula: str
    details: Mapping[str, object] = field(default_factory=dict)
    approximate: bool = False
    definition_version: str = METRIC_DEFINITION_VERSION

    def __post_init__(self) -> None:
        require_text(self.metric, "metric")
        require_text(self.subject, "subject")
        require_text(self.formula, "formula")
        require_text(self.definition_version, "definition_version")
        if not isinstance(self.family, MetricFamily):
            raise ValueError("family must be a MetricFamily")
        if not isinstance(self.scope, MetricScope):
            raise ValueError("scope must be a MetricScope")
        if not isinstance(self.status, MetricStatus):
            raise ValueError("status must be a MetricStatus")
        for value, name in ((self.numerator, "numerator"), (self.denominator, "denominator")):
            if value is not None:
                require_non_negative_int(value, name)
        if (
            self.numerator is not None
            and self.denominator is not None
            and self.numerator > self.denominator
        ):
            raise ValueError("numerator must not exceed denominator")
        if self.value is not None:
            _require_ratio(self.value, "value")
        if self.threshold is not None:
            _require_ratio(self.threshold, "threshold")
        if not isinstance(self.approximate, bool):
            raise ValueError("approximate must be a boolean")
        object.__setattr__(self, "details", dict(self.details or {}))

    def to_dict(self) -> dict[str, object]:
        return {
            "metric": self.metric,
            "family": self.family.value,
            "scope": self.scope.value,
            "subject": self.subject,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "value": self.value,
            "threshold": self.threshold,
            "status": self.status.value,
            "formula": self.formula,
            "definition_version": self.definition_version,
            "approximate": self.approximate,
            "details": dict(self.details),
        }


@dataclass(frozen=True, slots=True)
class ProfileWarning:
    """Sanitized, non-fatal profiling issue."""

    code: str
    message: str
    column: str | None = None
    rule_id: str | None = None
    details: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_text(self.code, "code")
        require_text(self.message, "message")
        if self.column is not None and not self.column.strip():
            raise ValueError("column must not be blank when provided")
        if self.rule_id is not None and not self.rule_id.strip():
            raise ValueError("rule_id must not be blank when provided")
        object.__setattr__(self, "details", dict(self.details or {}))

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "column": self.column,
            "rule_id": self.rule_id,
            "details": dict(self.details),
        }


@dataclass(frozen=True, slots=True)
class ValueCount:
    """Frequency of one canonical value or one null/empty marker."""

    label: str
    count: int
    is_null: bool = False
    is_empty: bool = False
    canonical: str = ""

    def __post_init__(self) -> None:
        require_positive_int(self.count, "count")
        if self.is_null and self.is_empty:
            raise ValueError("a count cannot be both null and empty")
        if self.is_null or self.is_empty:
            if self.label:
                raise ValueError("null/empty markers must use an empty label")
            object.__setattr__(self, "canonical", "null" if self.is_null else "empty")
        elif not self.label:
            raise ValueError("non-marker values must use a label")
        elif not self.canonical:
            object.__setattr__(self, "canonical", self.label)


@dataclass(frozen=True, slots=True)
class ChunkNumericState:
    """Mergeable finite-number state for one column in one chunk."""

    count: int
    total: float
    minimum: float | None
    maximum: float | None
    values: tuple[float, ...]
    non_finite_count: int = 0
    values_ref: str | None = None

    def __post_init__(self) -> None:
        require_non_negative_int(self.count, "count")
        require_non_negative_int(self.non_finite_count, "non_finite_count")
        object.__setattr__(self, "values", tuple(self.values))
        _require_finite(self.total, "total")
        for value in self.values:
            _require_finite(value, "numeric value")
        if self.values_ref is not None:
            require_text(self.values_ref, "values_ref")
            if self.values:
                raise ValueError("numeric state must hold values or a spill reference")
            if self.count == 0:
                raise ValueError("a spill reference requires at least one numeric value")
        elif self.count != len(self.values):
            raise ValueError("numeric count must match values")
        if self.count == 0:
            if self.minimum is not None or self.maximum is not None:
                raise ValueError("empty numeric state must not have minimum/maximum")
        elif self.minimum is None or self.maximum is None:
            raise ValueError("numeric state must provide minimum and maximum")
        if self.values and (self.minimum != min(self.values) or self.maximum != max(self.values)):
            raise ValueError("numeric minimum/maximum must match values")
        if self.minimum is not None:
            _require_finite(self.minimum, "minimum")
        if self.maximum is not None:
            _require_finite(self.maximum, "maximum")


@dataclass(frozen=True, slots=True)
class ChunkDateState:
    """Mergeable date state for one column in one chunk."""

    count: int
    minimum_epoch: float | None
    maximum_epoch: float | None
    minimum: str | None
    maximum: str | None
    timezone: str | None = None

    def __post_init__(self) -> None:
        require_non_negative_int(self.count, "count")
        if self.count == 0:
            if any(
                value is not None
                for value in (
                    self.minimum_epoch,
                    self.maximum_epoch,
                    self.minimum,
                    self.maximum,
                    self.timezone,
                )
            ):
                raise ValueError("empty date state must not have values")
            return
        if (
            self.minimum_epoch is None
            or self.maximum_epoch is None
            or self.minimum is None
            or self.maximum is None
        ):
            raise ValueError("date state must provide minimum and maximum")
        _require_finite(self.minimum_epoch, "minimum_epoch")
        _require_finite(self.maximum_epoch, "maximum_epoch")
        if self.minimum_epoch > self.maximum_epoch:
            raise ValueError("minimum_epoch must not exceed maximum_epoch")


@dataclass(frozen=True, slots=True)
class ChunkColumnState:
    """Mergeable state for one column in one chunk."""

    name: str
    dtype: str
    row_count: int
    null_count: int
    empty_count: int
    numeric: ChunkNumericState | None = None
    dates: ChunkDateState | None = None
    values: tuple[ValueCount, ...] = ()
    values_capped: bool = False
    failed: bool = False

    def __post_init__(self) -> None:
        require_text(self.name, "name")
        require_text(self.dtype, "dtype")
        require_non_negative_int(self.row_count, "row_count")
        require_non_negative_int(self.null_count, "null_count")
        require_non_negative_int(self.empty_count, "empty_count")
        if not isinstance(self.failed, bool):
            raise ValueError("failed must be a boolean")
        if self.null_count + self.empty_count > self.row_count:
            raise ValueError("null and empty counts must not exceed row_count")
        object.__setattr__(self, "values", tuple(self.values))
        if len({(item.canonical, item.is_null, item.is_empty) for item in self.values}) != len(
            self.values
        ):
            raise ValueError("value counts must be unique")
        if not isinstance(self.values_capped, bool):
            raise ValueError("values_capped must be a boolean")


@dataclass(frozen=True, slots=True)
class RuleChunkState:
    """Mergeable counts or key hashes for one declared rule."""

    rule_id: str
    numerator: int
    denominator: int
    key_hashes: tuple[str, ...] = ()
    key_hashes_capped: bool = False

    def __post_init__(self) -> None:
        require_text(self.rule_id, "rule_id")
        require_non_negative_int(self.numerator, "numerator")
        require_non_negative_int(self.denominator, "denominator")
        if self.numerator > self.denominator:
            raise ValueError("numerator must not exceed denominator")
        object.__setattr__(self, "key_hashes", tuple(self.key_hashes))
        if any(not value.strip() for value in self.key_hashes):
            raise ValueError("key hashes must not be blank")
        if self.key_hashes and self.numerator != len(set(self.key_hashes)):
            raise ValueError("key-hash numerator must match the chunk's distinct keys")
        if self.key_hashes and self.denominator < len(self.key_hashes):
            raise ValueError("key-hash denominator must cover the chunk's keys")
        if not isinstance(self.key_hashes_capped, bool):
            raise ValueError("key_hashes_capped must be a boolean")


@dataclass(frozen=True, slots=True)
class ChunkProfile:
    """Per-chunk profiling record suitable for later merging."""

    chunk_index: int
    row_count: int
    complete_rows: int
    columns: tuple[ChunkColumnState, ...]
    row_hashes: tuple[str, ...] = ()
    row_hashes_capped: bool = False
    rules: tuple[RuleChunkState, ...] = ()
    warnings: tuple[ProfileWarning, ...] = ()

    def __post_init__(self) -> None:
        require_non_negative_int(self.chunk_index, "chunk_index")
        require_non_negative_int(self.row_count, "row_count")
        require_non_negative_int(self.complete_rows, "complete_rows")
        if self.complete_rows > self.row_count:
            raise ValueError("complete_rows must not exceed row_count")
        object.__setattr__(self, "columns", tuple(self.columns))
        object.__setattr__(self, "row_hashes", tuple(self.row_hashes))
        object.__setattr__(self, "rules", tuple(self.rules))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        names = [column.name for column in self.columns]
        if len(names) != len(set(names)):
            raise ValueError("column names must be unique")
        if any(not value.strip() for value in self.row_hashes):
            raise ValueError("row hashes must not be blank")
        if len({rule.rule_id for rule in self.rules}) != len(self.rules):
            raise ValueError("rule ids must be unique per chunk")
        if not isinstance(self.row_hashes_capped, bool):
            raise ValueError("row_hashes_capped must be a boolean")

    def to_dict(self) -> dict[str, object]:
        return {
            "chunk_index": self.chunk_index,
            "row_count": self.row_count,
            "complete_rows": self.complete_rows,
            "row_hashes": list(self.row_hashes),
            "row_hashes_capped": self.row_hashes_capped,
            "columns": [
                {
                    "name": column.name,
                    "dtype": column.dtype,
                    "row_count": column.row_count,
                    "null_count": column.null_count,
                    "empty_count": column.empty_count,
                    "numeric": (
                        None
                        if column.numeric is None
                        else {
                            "count": column.numeric.count,
                            "total": column.numeric.total,
                            "minimum": column.numeric.minimum,
                            "maximum": column.numeric.maximum,
                            "values": list(column.numeric.values),
                            "values_ref": column.numeric.values_ref,
                            "non_finite_count": column.numeric.non_finite_count,
                        }
                    ),
                    "dates": (
                        None
                        if column.dates is None
                        else {
                            "count": column.dates.count,
                            "minimum_epoch": column.dates.minimum_epoch,
                            "maximum_epoch": column.dates.maximum_epoch,
                            "minimum": column.dates.minimum,
                            "maximum": column.dates.maximum,
                            "timezone": column.dates.timezone,
                        }
                    ),
                    "values": [
                        {
                            "label": item.label,
                            "count": item.count,
                            "is_null": item.is_null,
                            "is_empty": item.is_empty,
                            "canonical": item.canonical,
                        }
                        for item in column.values
                    ],
                    "values_capped": column.values_capped,
                    "failed": column.failed,
                }
                for column in self.columns
            ],
            "rules": [
                {
                    "rule_id": rule.rule_id,
                    "numerator": rule.numerator,
                    "denominator": rule.denominator,
                    "key_hashes": list(rule.key_hashes),
                    "key_hashes_capped": rule.key_hashes_capped,
                }
                for rule in self.rules
            ],
            "warnings": [warning.to_dict() for warning in self.warnings],
        }


@dataclass(frozen=True, slots=True)
class NumericStatistics:
    """Final statistical summary for a numeric column."""

    count: int
    total: float
    minimum: float | None
    maximum: float | None
    mean: float | None
    median: float | None
    mode: tuple[float, ...]
    non_finite_count: int = 0
    approximate: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "count": self.count,
            "total": self.total,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "mean": self.mean,
            "median": self.median,
            "mode": list(self.mode),
            "non_finite_count": self.non_finite_count,
            "approximate": self.approximate,
        }


@dataclass(frozen=True, slots=True)
class DateTimeStatistics:
    """Final date summary with ISO 8601 boundaries and duration."""

    count: int
    minimum: str | None
    maximum: str | None
    range_seconds: float | None
    range_iso: str | None = None
    timezone: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "count": self.count,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "range_seconds": self.range_seconds,
            "range_iso": self.range_iso,
            "timezone": self.timezone,
        }


@dataclass(frozen=True, slots=True)
class CategoricalStatistics:
    """Frequency table and distinct estimate for a categorical column."""

    frequencies: tuple[ValueCount, ...]
    distinct_count: int
    capped: bool = False
    truncated: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "frequencies": [
                {
                    "label": item.label,
                    "count": item.count,
                    "is_null": item.is_null,
                    "is_empty": item.is_empty,
                    "canonical": item.canonical,
                }
                for item in self.frequencies
            ],
            "distinct_count": self.distinct_count,
            "capped": self.capped,
            "truncated": self.truncated,
        }


@dataclass(frozen=True, slots=True)
class ColumnStatistics:
    """Final statistics for one source column."""

    name: str
    dtype: str
    row_count: int
    null_count: int
    empty_count: int
    numeric: NumericStatistics | None = None
    dates: DateTimeStatistics | None = None
    categorical: CategoricalStatistics | None = None
    distinct_count: int = 0
    distinct_capped: bool = False

    @property
    def present_count(self) -> int:
        return self.row_count - self.null_count - self.empty_count

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "dtype": self.dtype,
            "row_count": self.row_count,
            "null_count": self.null_count,
            "empty_count": self.empty_count,
            "present_count": self.present_count,
            "distinct_count": self.distinct_count,
            "distinct_capped": self.distinct_capped,
            "numeric": None if self.numeric is None else self.numeric.to_dict(),
            "dates": None if self.dates is None else self.dates.to_dict(),
            "categorical": None if self.categorical is None else self.categorical.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ProfileReport:
    """Merged profile and quality report for one source."""

    run_id: str
    source_id: str
    source_type: SourceType
    row_count: int
    chunk_count: int
    chunk_size: int
    scope: ProfileScope
    method: str
    merge_method: str
    approximate: bool
    columns: tuple[ColumnStatistics, ...]
    metrics: tuple[MetricResult, ...]
    warnings: tuple[ProfileWarning, ...] = ()
    content_hash: str | None = None
    schema_hash: str | None = None
    metric_definition_version: str = METRIC_DEFINITION_VERSION

    def __post_init__(self) -> None:
        for value, name in (
            (self.run_id, "run_id"),
            (self.source_id, "source_id"),
            (self.method, "method"),
            (self.merge_method, "merge_method"),
            (self.metric_definition_version, "metric_definition_version"),
        ):
            require_text(value, name)
        if self.source_type not in SOURCE_TYPES:
            raise ValueError(f"unsupported source_type: {self.source_type}")
        require_non_negative_int(self.row_count, "row_count")
        require_non_negative_int(self.chunk_count, "chunk_count")
        require_positive_int(self.chunk_size, "chunk_size")
        if not isinstance(self.scope, ProfileScope):
            raise ValueError("scope must be a ProfileScope")
        if not isinstance(self.approximate, bool):
            raise ValueError("approximate must be a boolean")
        object.__setattr__(self, "columns", tuple(self.columns))
        object.__setattr__(self, "metrics", tuple(self.metrics))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        if len({column.name for column in self.columns}) != len(self.columns):
            raise ValueError("column names must be unique")
        if len({(metric.metric, metric.subject) for metric in self.metrics}) != len(self.metrics):
            raise ValueError("metric name/subject pairs must be unique")
        if self.content_hash is not None and not self.content_hash.strip():
            raise ValueError("content_hash must not be blank when provided")
        if self.schema_hash is not None and not self.schema_hash.strip():
            raise ValueError("schema_hash must not be blank when provided")

    def to_info_dict(self) -> dict[str, object]:
        """Build the JSON-compatible info document."""
        return {
            "schema_version": PROFILE_SCHEMA_VERSION,
            "metric_definition_version": self.metric_definition_version,
            "run_id": self.run_id,
            "source": {
                "source_id": self.source_id,
                "source_type": self.source_type,
                "content_hash": self.content_hash,
                "schema_hash": self.schema_hash,
                "row_count": self.row_count,
            },
            "profile": {
                "scope": self.scope.value,
                "method": self.method,
                "approximate": self.approximate,
                "chunk_merge_method": self.merge_method,
                "chunk_count": self.chunk_count,
                "chunk_size": self.chunk_size,
            },
            "columns": [column.to_dict() for column in self.columns],
            "quality": {
                "metrics": [metric.to_dict() for metric in self.metrics],
                "warnings": [warning.to_dict() for warning in self.warnings],
            },
        }


__all__ = [
    "METRIC_DEFINITION_VERSION",
    "PROFILE_SCHEMA_VERSION",
    "CategoricalStatistics",
    "ChunkColumnState",
    "ChunkDateState",
    "ChunkNumericState",
    "ChunkProfile",
    "ColumnStatistics",
    "DateTimeStatistics",
    "MetricFamily",
    "MetricResult",
    "MetricScope",
    "MetricStatus",
    "NumericStatistics",
    "ProfileReport",
    "ProfileScope",
    "ProfileWarning",
    "QualityRule",
    "RuleChunkState",
    "RuleKind",
    "ValueCount",
]
