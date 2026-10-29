"""Unit tests for assessment value objects."""

from __future__ import annotations

import pytest

from domain.entities.assessment import (
    AssessmentIssue,
    AssessmentMetric,
    AssessmentReport,
    DraftPlan,
)
from domain.entities.plan import PlanChunking, PlanTransformation
from domain.entities.profiling import MetricStatus


def _draft() -> DraftPlan:
    return DraftPlan(
        name="assess_src",
        description="Assess the source",
        source_operation="read_csv",
        source_params={"path": "input.csv"},
        transformations=(
            PlanTransformation(
                step_id="drop_duplicates",
                operation="drop_duplicate_rows",
                params={"subset": ["id"], "keep": "first"},
            ),
        ),
        chunking=PlanChunking(enabled=True, size=1000),
        rationale=("Duplicate rows were detected.",),
    )


def _report(**overrides: object) -> AssessmentReport:
    values: dict[str, object] = {
        "assessment_id": "asm_run-1",
        "run_id": "run-1",
        "source_id": "src_abc",
        "source_type": "csv",
        "row_count": 2,
        "column_count": 1,
        "content_hash": "sha256:abc",
        "schema_hash": "sha256:def",
        "issues": (
            AssessmentIssue(
                code="DUPLICATE_ROWS",
                message="Duplicate rows",
                severity="warning",
            ),
        ),
        "assumptions": ("The source was read fully.",),
        "missing_inputs": ("destination",),
        "draft_plan": _draft(),
        "quality": (
            AssessmentMetric(
                metric="duplicate_rows",
                subject="*",
                value=0.5,
                status=MetricStatus.FAIL,
            ),
        ),
        "quality_path": "artifacts/run-1/quality.csv",
        "info_path": "artifacts/run-1/info.json",
        "chunk_count": 1,
    }
    values.update(overrides)
    return AssessmentReport(**values)  # type: ignore[arg-type]


def test_assessment_report_serializes_findings_and_draft() -> None:
    payload = _report().to_dict()

    assert payload["assessment_id"] == "asm_run-1"
    assert payload["missing_inputs"] == ["destination"]
    assert payload["issues"][0]["severity"] == "warning"  # type: ignore[index]
    assert payload["quality"][0]["status"] == "fail"  # type: ignore[index]
    assert payload["draft_plan"]["source_operation"] == "read_csv"  # type: ignore[index]


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"source_type": "xml"}, "unsupported source_type"),
        ({"row_count": -1}, "row_count"),
        ({"column_count": -1}, "column_count"),
        ({"chunk_count": -1}, "chunk_count"),
        ({"schema_hash": " "}, "schema_hash"),
        ({"assumptions": (" ",)}, "assumptions"),
        ({"missing_inputs": (" ",)}, "missing_inputs"),
        ({"quality_path": " "}, "quality_path"),
        ({"info_path": " "}, "info_path"),
        ({"draft_plan": object()}, "draft_plan"),
    ],
)
def test_assessment_report_rejects_invalid_values(
    overrides: dict[str, object],
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        _report(**overrides)


def test_assessment_issue_and_metric_validate_values() -> None:
    with pytest.raises(ValueError, match="severity"):
        AssessmentIssue(code="X", message="x", severity="critical")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="between 0 and 1"):
        AssessmentMetric(
            metric="m",
            subject="*",
            value=2.0,
            status=MetricStatus.FAIL,
        )
    with pytest.raises(ValueError, match="status"):
        AssessmentMetric(
            metric="m",
            subject="*",
            value=1.0,
            status="fail",  # type: ignore[arg-type]
        )
