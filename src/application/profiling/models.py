"""Application-level profiling policy and request models."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from domain.entities._validation import require_positive_int, require_text
from domain.entities.ingestion import SOURCE_TYPES, SourceType
from domain.entities.profiling import (
    MetricFamily,
    ProfileReport,
    ProfileScope,
    QualityRule,
)


@dataclass(frozen=True, slots=True)
class ProfileLimits:
    """Bounds that keep exact profiling maps from exhausting memory."""

    max_distinct_values: int = 100_000
    max_row_hashes: int = 100_000
    max_frequency_rows: int = 100

    def __post_init__(self) -> None:
        for value, name in (
            (self.max_distinct_values, "max_distinct_values"),
            (self.max_row_hashes, "max_row_hashes"),
            (self.max_frequency_rows, "max_frequency_rows"),
        ):
            require_positive_int(value, name)


@dataclass(frozen=True, slots=True)
class ProfileThresholds:
    """Minimum acceptable ratio for each quality family."""

    completeness: float = 1.0
    uniqueness: float = 1.0
    consistency: float = 1.0
    validity: float = 1.0

    def __post_init__(self) -> None:
        for value, name in (
            (self.completeness, "completeness"),
            (self.uniqueness, "uniqueness"),
            (self.consistency, "consistency"),
            (self.validity, "validity"),
        ):
            if not math.isfinite(value) or value < 0 or value > 1:
                raise ValueError(f"{name} threshold must be between 0 and 1")

    def for_family(self, family: MetricFamily) -> float | None:
        if family is MetricFamily.COMPLETENESS:
            return self.completeness
        if family is MetricFamily.UNIQUENESS:
            return self.uniqueness
        if family is MetricFamily.CONSISTENCY:
            return self.consistency
        if family is MetricFamily.VALIDITY:
            return self.validity
        return None


@dataclass(frozen=True, slots=True)
class ProfileRequest:
    """Inputs that determine scope, merge policy, rules, and thresholds."""

    run_id: str
    source_id: str
    source_type: SourceType
    scope: ProfileScope = ProfileScope.FULL
    method: str = "streaming_chunks"
    merge_method: str = "additive_counts+exact_values+frequency_maps+row_hashes"
    chunk_size: int = 10_000
    approximate: bool = False
    thresholds: ProfileThresholds = field(default_factory=ProfileThresholds)
    limits: ProfileLimits = field(default_factory=ProfileLimits)
    rules: tuple[QualityRule, ...] = ()
    content_hash: str | None = None
    schema_hash: str | None = None

    def __post_init__(self) -> None:
        require_text(self.run_id, "run_id")
        require_text(self.source_id, "source_id")
        if self.source_type not in SOURCE_TYPES:
            raise ValueError(f"unsupported source_type: {self.source_type}")
        if not isinstance(self.scope, ProfileScope):
            raise ValueError("scope must be a ProfileScope")
        require_text(self.method, "method")
        require_text(self.merge_method, "merge_method")
        require_positive_int(self.chunk_size, "chunk_size")
        if not isinstance(self.approximate, bool):
            raise ValueError("approximate must be a boolean")
        if self.scope is ProfileScope.SAMPLE and not self.approximate:
            raise ValueError("sample profiles must be marked approximate")
        if not isinstance(self.thresholds, ProfileThresholds):
            raise ValueError("thresholds must be ProfileThresholds")
        if not isinstance(self.limits, ProfileLimits):
            raise ValueError("limits must be ProfileLimits")
        object.__setattr__(self, "rules", tuple(self.rules))
        if any(not isinstance(rule, QualityRule) for rule in self.rules):
            raise ValueError("rules must be QualityRule values")
        if len({rule.rule_id for rule in self.rules}) != len(self.rules):
            raise ValueError("rule ids must be unique")
        if self.content_hash is not None and not self.content_hash.strip():
            raise ValueError("content_hash must not be blank when provided")
        if self.schema_hash is not None and not self.schema_hash.strip():
            raise ValueError("schema_hash must not be blank when provided")

    def rule_threshold(self, rule: QualityRule) -> float | None:
        if rule.threshold is not None:
            return rule.threshold
        return self.thresholds.for_family(rule.family)


@dataclass(frozen=True, slots=True)
class ProfileArtifacts:
    """Paths written for one profiling run."""

    quality_path: str
    info_path: str
    chunk_paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProfileOutcome:
    """Merged report plus written artifact locations."""

    report: ProfileReport
    artifacts: ProfileArtifacts


__all__ = [
    "ProfileArtifacts",
    "ProfileLimits",
    "ProfileOutcome",
    "ProfileRequest",
    "ProfileThresholds",
]
