"""Derive assessment findings and a conservative draft plan from a profile."""

from __future__ import annotations

import re

from application.assessment.models import SourceDescriptor
from application.profiling.models import ProfileArtifacts
from domain.entities.assessment import (
    AssessmentIssue,
    AssessmentMetric,
    AssessmentReport,
    DraftPlan,
)
from domain.entities.plan import PlanChunking, PlanTransformation
from domain.entities.profiling import (
    ColumnStatistics,
    MetricResult,
    MetricStatus,
    ProfileReport,
)

_SAFE_COLUMN_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")


def build_assessment_report(
    *,
    run_id: str,
    source: SourceDescriptor,
    profile: ProfileReport,
    artifacts: ProfileArtifacts,
    chunk_size: int,
) -> AssessmentReport:
    """Build the v1 assessment report from one validated profile."""
    issues = _findings(profile)
    return AssessmentReport(
        assessment_id=f"asm_{run_id}",
        run_id=run_id,
        source_id=source.source_id,
        source_type=source.source_type,
        row_count=profile.row_count,
        column_count=len(profile.columns),
        content_hash=profile.content_hash or source.content_hash,
        schema_hash=profile.schema_hash,
        issues=issues,
        assumptions=_assumptions(profile, chunk_size),
        missing_inputs=("destination",),
        draft_plan=_draft_plan(source, profile, chunk_size=chunk_size),
        quality=_selected_metrics(profile),
        quality_path=artifacts.quality_path,
        info_path=artifacts.info_path,
        chunk_count=profile.chunk_count,
    )


def _findings(profile: ProfileReport) -> tuple[AssessmentIssue, ...]:
    issues: list[AssessmentIssue] = []
    if profile.row_count == 0:
        issues.append(
            AssessmentIssue(
                code="SOURCE_EMPTY",
                message="The source contains no rows",
                severity="error",
            )
        )
    duplicate = _metric(profile, "duplicate_rows")
    if duplicate is not None and duplicate.value is not None and duplicate.value < 1.0:
        duplicate_count = duplicate.details.get("duplicate_row_count", 0)
        issues.append(
            AssessmentIssue(
                code="DUPLICATE_ROWS",
                message="The source contains duplicate rows",
                severity="warning",
                details={
                    "duplicate_row_count": (
                        duplicate_count if isinstance(duplicate_count, int) else 0
                    ),
                    "distinct_row_count": duplicate.numerator,
                },
            )
        )
    for column in profile.columns:
        issues.extend(_column_findings(column))
    if profile.approximate:
        issues.append(
            AssessmentIssue(
                code="PROFILE_APPROXIMATE",
                message="At least one profile metric was capped and is approximate",
                severity="info",
            )
        )
    return tuple(issues)


def _column_findings(column: ColumnStatistics) -> list[AssessmentIssue]:
    issues: list[AssessmentIssue] = []
    if column.row_count > 0 and column.present_count == 0:
        issues.append(
            AssessmentIssue(
                code="COLUMN_ALL_NULL",
                message="The column contains no present values",
                severity="error",
                column=column.name,
                details={"row_count": column.row_count},
            )
        )
    elif column.null_count + column.empty_count > 0:
        issues.append(
            AssessmentIssue(
                code="COLUMN_MISSING_VALUES",
                message="The column contains null or empty values",
                severity="warning",
                column=column.name,
                details={
                    "null_count": column.null_count,
                    "empty_count": column.empty_count,
                },
            )
        )
    if column.numeric is not None and column.numeric.non_finite_count > 0:
        issues.append(
            AssessmentIssue(
                code="NON_FINITE_NUMERIC_VALUES",
                message="The numeric column contains non-finite values",
                severity="warning",
                column=column.name,
                details={"count": column.numeric.non_finite_count},
            )
        )
    if column.distinct_capped:
        issues.append(
            AssessmentIssue(
                code="COLUMN_DISTINCT_CAPPED",
                message="Distinct-value tracking for the column reached its limit",
                severity="info",
                column=column.name,
            )
        )
    if column.categorical is not None and column.categorical.truncated:
        issues.append(
            AssessmentIssue(
                code="COLUMN_FREQUENCY_TRUNCATED",
                message="The column frequency table was truncated",
                severity="info",
                column=column.name,
            )
        )
    return issues


def _assumptions(profile: ProfileReport, chunk_size: int) -> tuple[str, ...]:
    return (
        (
            f"The source was read with a full scan in {profile.chunk_count} chunk(s) "
            f"of up to {chunk_size} rows."
        ),
        "Assessment is read-only and did not write to a destination.",
        "Candidate transformations are conservative and require explicit confirmation.",
    )


def _draft_plan(
    source: SourceDescriptor,
    profile: ProfileReport,
    *,
    chunk_size: int,
) -> DraftPlan:
    transformations: list[PlanTransformation] = []
    rationale: list[str] = []
    column_names = [column.name for column in profile.columns]
    duplicate = _metric(profile, "duplicate_rows")
    if (
        column_names
        and duplicate is not None
        and duplicate.value is not None
        and duplicate.value < 1.0
    ):
        transformations.append(
            PlanTransformation(
                step_id="drop_duplicates",
                operation="drop_duplicate_rows",
                params={"subset": column_names, "keep": "first"},
            )
        )
        rationale.append(
            "Duplicate rows were detected; drop_duplicate_rows is deterministic and idempotent."
        )
    if any(not _SAFE_COLUMN_NAME.fullmatch(name) for name in column_names):
        transformations.append(
            PlanTransformation(
                step_id="standardize_columns",
                operation="standardize_column_names",
                params={"case": "lower"},
            )
        )
        rationale.append(
            "Non-standard column names were detected; standardize_column_names normalizes them."
        )
    if not transformations:
        rationale.append("No transformation candidates were derived from the v1 profile.")

    path = str(source.params.get("path", source.source_id))
    return DraftPlan(
        name=f"assess_{source.source_id}",
        description=f"Load {path} after read-only assessment",
        source_operation=source.operation,
        source_params=dict(source.params),
        transformations=tuple(transformations),
        chunking=PlanChunking(enabled=True, size=chunk_size),
        rationale=tuple(rationale),
    )


def _selected_metrics(profile: ProfileReport) -> tuple[AssessmentMetric, ...]:
    selected = [
        metric
        for metric in profile.metrics
        if metric.subject == "*" or metric.status is MetricStatus.FAIL
    ]
    return tuple(_assessment_metric(metric) for metric in selected)


def _assessment_metric(metric: MetricResult) -> AssessmentMetric:
    return AssessmentMetric(
        metric=metric.metric,
        subject=metric.subject,
        value=metric.value,
        status=metric.status,
        approximate=metric.approximate,
    )


def _metric(
    profile: ProfileReport,
    metric: str,
    subject: str = "*",
) -> MetricResult | None:
    for item in profile.metrics:
        if item.metric == metric and item.subject == subject:
            return item
    return None


__all__ = ["build_assessment_report"]
