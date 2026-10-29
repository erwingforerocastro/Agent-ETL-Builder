"""Assessment findings and draft-plan value objects."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final, Literal

from domain.entities._validation import (
    require_non_negative_int,
    require_text,
)
from domain.entities.ingestion import SOURCE_TYPES, SourceType
from domain.entities.plan import PlanChunking, PlanTransformation
from domain.entities.profiling import MetricStatus

AssessmentSeverity = Literal["info", "warning", "error"]
SEVERITIES: Final[frozenset[str]] = frozenset({"info", "warning", "error"})


@dataclass(frozen=True, slots=True)
class AssessmentIssue:
    """One validated finding derived from a source profile."""

    code: str
    message: str
    severity: AssessmentSeverity
    column: str | None = None
    details: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_text(self.code, "code")
        require_text(self.message, "message")
        if self.severity not in SEVERITIES:
            raise ValueError("severity must be info, warning, or error")
        if self.column is not None and not self.column.strip():
            raise ValueError("column must not be blank when provided")
        object.__setattr__(self, "details", dict(self.details or {}))

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "column": self.column,
            "details": dict(self.details),
        }


@dataclass(frozen=True, slots=True)
class AssessmentMetric:
    """Selected quality metric retained in the assessment summary."""

    metric: str
    subject: str
    value: float | None
    status: MetricStatus
    approximate: bool = False

    def __post_init__(self) -> None:
        require_text(self.metric, "metric")
        require_text(self.subject, "subject")
        if not isinstance(self.status, MetricStatus):
            raise ValueError("status must be a MetricStatus")
        if self.value is not None and (not math.isfinite(self.value) or not 0 <= self.value <= 1):
            raise ValueError("value must be between 0 and 1")
        if not isinstance(self.approximate, bool):
            raise ValueError("approximate must be a boolean")

    def to_dict(self) -> dict[str, object]:
        return {
            "metric": self.metric,
            "subject": self.subject,
            "value": self.value,
            "status": self.status.value,
            "approximate": self.approximate,
        }


@dataclass(frozen=True, slots=True)
class DraftPlan:
    """A safe, non-executable draft pipeline plan awaiting confirmation."""

    name: str
    description: str
    source_operation: str
    source_params: Mapping[str, object]
    transformations: tuple[PlanTransformation, ...]
    chunking: PlanChunking
    rationale: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_text(self.name, "name")
        require_text(self.description, "description")
        require_text(self.source_operation, "source_operation")
        object.__setattr__(self, "source_params", dict(self.source_params))
        object.__setattr__(self, "transformations", tuple(self.transformations))
        if not isinstance(self.chunking, PlanChunking):
            raise ValueError("chunking must be a PlanChunking")
        object.__setattr__(self, "rationale", tuple(self.rationale))
        if any(not item.strip() for item in self.rationale):
            raise ValueError("rationale entries must not be blank")

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "source_operation": self.source_operation,
            "source_params": dict(self.source_params),
            "transformations": [
                {
                    "step_id": step.step_id,
                    "operation": step.operation,
                    "params": dict(step.params),
                }
                for step in self.transformations
            ],
            "chunking": {
                "enabled": self.chunking.enabled,
                "size": self.chunking.size,
            },
            "rationale": list(self.rationale),
        }


@dataclass(frozen=True, slots=True)
class AssessmentReport:
    """Read-only findings and a draft plan for one source."""

    assessment_id: str
    run_id: str
    source_id: str
    source_type: SourceType
    row_count: int
    column_count: int
    content_hash: str
    schema_hash: str | None
    issues: tuple[AssessmentIssue, ...]
    assumptions: tuple[str, ...]
    missing_inputs: tuple[str, ...]
    draft_plan: DraftPlan
    quality: tuple[AssessmentMetric, ...] = ()
    quality_path: str | None = None
    info_path: str | None = None
    chunk_count: int = 0

    def __post_init__(self) -> None:
        for value, name in (
            (self.assessment_id, "assessment_id"),
            (self.run_id, "run_id"),
            (self.source_id, "source_id"),
            (self.content_hash, "content_hash"),
        ):
            require_text(value, name)
        if self.source_type not in SOURCE_TYPES:
            raise ValueError(f"unsupported source_type: {self.source_type}")
        require_non_negative_int(self.row_count, "row_count")
        require_non_negative_int(self.column_count, "column_count")
        require_non_negative_int(self.chunk_count, "chunk_count")
        if self.schema_hash is not None and not self.schema_hash.strip():
            raise ValueError("schema_hash must not be blank when provided")
        object.__setattr__(self, "issues", tuple(self.issues))
        object.__setattr__(self, "assumptions", tuple(self.assumptions))
        object.__setattr__(self, "missing_inputs", tuple(self.missing_inputs))
        object.__setattr__(self, "quality", tuple(self.quality))
        if not isinstance(self.draft_plan, DraftPlan):
            raise ValueError("draft_plan must be a DraftPlan")
        if any(not item.strip() for item in self.assumptions):
            raise ValueError("assumptions must not be blank")
        if any(not item.strip() for item in self.missing_inputs):
            raise ValueError("missing_inputs must not be blank")
        if self.quality_path is not None and not self.quality_path.strip():
            raise ValueError("quality_path must not be blank when provided")
        if self.info_path is not None and not self.info_path.strip():
            raise ValueError("info_path must not be blank when provided")

    def to_dict(self) -> dict[str, object]:
        return {
            "assessment_id": self.assessment_id,
            "run_id": self.run_id,
            "source_id": self.source_id,
            "source_type": self.source_type,
            "row_count": self.row_count,
            "column_count": self.column_count,
            "content_hash": self.content_hash,
            "schema_hash": self.schema_hash,
            "issues": [issue.to_dict() for issue in self.issues],
            "assumptions": list(self.assumptions),
            "missing_inputs": list(self.missing_inputs),
            "quality": [metric.to_dict() for metric in self.quality],
            "draft_plan": self.draft_plan.to_dict(),
            "quality_path": self.quality_path,
            "info_path": self.info_path,
            "chunk_count": self.chunk_count,
        }


__all__ = [
    "SEVERITIES",
    "AssessmentIssue",
    "AssessmentMetric",
    "AssessmentReport",
    "AssessmentSeverity",
    "DraftPlan",
]
