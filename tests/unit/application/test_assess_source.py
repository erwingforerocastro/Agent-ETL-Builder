"""Unit tests for source assessment and draft confirmation."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator

import pandas as pd
import pytest

from application.assessment.assess_source import AssessSourceUseCase
from application.assessment.confirmation import build_pipeline_plan
from application.assessment.models import AssessmentSettings, SourceDescriptor
from application.profiling.models import (
    ProfileArtifacts,
    ProfileLimits,
    ProfileOutcome,
    ProfileRequest,
)
from domain.entities.assessment import AssessmentReport
from infrastructure.profiling.pandas_profiler import PandasChunkProfiler


class _Reader:
    def __init__(self, frames: list[pd.DataFrame]) -> None:
        self._frames = frames
        self.chunk_calls: list[int] = []

    def describe(self, reference: str) -> SourceDescriptor:
        assert reference == "input.csv"
        return SourceDescriptor(
            source_id="src_abc",
            source_type="csv",
            operation="read_csv",
            params={"path": "input.csv"},
            path="input.csv",
            content_hash="sha256:source",
        )

    def iter_chunks(
        self,
        source: SourceDescriptor,
        *,
        chunk_size: int,
    ) -> Iterator[pd.DataFrame]:
        del source
        self.chunk_calls.append(chunk_size)
        yield from self._frames


class _Profiler:
    def __init__(self, limits: ProfileLimits | None = None) -> None:
        self._profiler = PandasChunkProfiler(limits)
        self.request: ProfileRequest | None = None

    def execute(
        self,
        chunks: Iterable[object],
        request: ProfileRequest,
    ) -> ProfileOutcome:
        self.request = request
        records = [
            self._profiler.profile_chunk(chunk, chunk_index=index)
            for index, chunk in enumerate(chunks)
        ]
        return ProfileOutcome(
            report=self._profiler.merge(records, request=request),
            artifacts=ProfileArtifacts(
                quality_path="artifacts/run-1/quality.csv",
                info_path="artifacts/run-1/info.json",
                chunk_paths=("chunk-0.json", "chunk-1.json"),
            ),
        )


def _assess() -> tuple[AssessmentReport, _Profiler, _Reader]:
    return _assess_frames(
        [
            pd.DataFrame(
                {
                    "id": [1, 1],
                    "name": ["Ada", ""],
                    "amount": [1.0, None],
                    "note": [None, None],
                }
            ),
            pd.DataFrame(
                {
                    "id": [1, 2],
                    "name": ["Ada", "Cyd"],
                    "amount": [1.0, 4.0],
                    "note": [None, None],
                }
            ),
        ]
    )


def _assess_frames(
    frames: list[pd.DataFrame],
    *,
    limits: ProfileLimits | None = None,
) -> tuple[AssessmentReport, _Profiler, _Reader]:
    reader = _Reader(frames)
    profiler = _Profiler(limits)
    use_case = AssessSourceUseCase(
        reader,
        profiler,
        AssessmentSettings(chunk_size=2),
    )
    return use_case.execute(run_id="run-1", reference="input.csv"), profiler, reader


def test_assessment_reports_findings_and_a_draft_plan() -> None:
    report, profiler, reader = _assess()

    assert report.assessment_id == "asm_run-1"
    assert report.source_id == "src_abc"
    assert report.row_count == 4
    assert report.column_count == 4
    assert report.chunk_count == 2
    assert report.content_hash == "sha256:source"
    assert report.quality_path == "artifacts/run-1/quality.csv"
    assert report.info_path == "artifacts/run-1/info.json"
    assert report.missing_inputs == ("destination",)
    assert reader.chunk_calls == [2]
    assert profiler.request is not None
    assert profiler.request.chunk_size == 2
    assert profiler.request.content_hash == "sha256:source"

    issue_codes = {issue.code for issue in report.issues}
    assert "DUPLICATE_ROWS" in issue_codes
    assert "COLUMN_ALL_NULL" in issue_codes
    assert "COLUMN_MISSING_VALUES" in issue_codes

    candidates = {step.operation for step in report.draft_plan.transformations}
    assert candidates == {"drop_duplicate_rows"}
    assert report.draft_plan.source_params == {"path": "input.csv"}
    assert any("full scan" in assumption for assumption in report.assumptions)
    assert {metric.metric for metric in report.quality} >= {"duplicate_rows"}


def test_confirm_builds_a_pipeline_plan_with_a_destination() -> None:
    report, _, _ = _assess()

    plan = build_pipeline_plan(report, destination="output.csv")

    assert plan.mode == "pipeline"
    assert plan.run_id == "run-1"
    assert plan.source is not None
    assert plan.source.operation == "read_csv"
    assert plan.source.params == {"path": "input.csv"}
    assert plan.destination is not None
    assert plan.destination.operation == "save_csv"
    assert plan.destination.params == {"path": "output.csv"}
    assert plan.approval_required is True
    assert [step.operation for step in plan.transformations] == ["drop_duplicate_rows"]


def test_empty_source_reports_no_rows_and_no_candidates() -> None:
    report, _, _ = _assess_frames([pd.DataFrame()])

    assert report.row_count == 0
    assert report.column_count == 0
    assert report.schema_hash is None
    assert {issue.code for issue in report.issues} == {"SOURCE_EMPTY"}
    assert report.draft_plan.transformations == ()
    assert report.draft_plan.rationale == (
        "No transformation candidates were derived from the v1 profile.",
    )


def test_non_finite_values_and_non_standard_columns_are_reported() -> None:
    report, _, _ = _assess_frames(
        [
            pd.DataFrame(
                {
                    "First Name": ["Ada", "Bob"],
                    "score": [1.0, float("inf")],
                }
            )
        ]
    )

    issue_codes = {issue.code for issue in report.issues}
    assert "NON_FINITE_NUMERIC_VALUES" in issue_codes
    assert [step.operation for step in report.draft_plan.transformations] == [
        "standardize_column_names"
    ]


def test_capped_profile_is_marked_approximate() -> None:
    report, _, _ = _assess_frames(
        [pd.DataFrame({"category": ["a", "b", "c"]})],
        limits=ProfileLimits(max_tracked_values=2, max_frequency_rows=1),
    )

    issue_codes = {issue.code for issue in report.issues}
    assert "PROFILE_APPROXIMATE" in issue_codes
    assert "COLUMN_DISTINCT_CAPPED" in issue_codes
    assert "COLUMN_FREQUENCY_TRUNCATED" in issue_codes


@pytest.mark.parametrize("destination", [" ", "input.csv", "./input.csv"])
def test_confirm_rejects_blank_or_source_overwriting_destinations(destination: str) -> None:
    report, _, _ = _assess()

    with pytest.raises(ValueError, match="destination"):
        build_pipeline_plan(report, destination=destination)


def test_assessment_settings_require_a_positive_chunk_size() -> None:
    with pytest.raises(ValueError, match="chunk_size"):
        AssessmentSettings(chunk_size=0)


def test_assessment_runs_inside_the_sandbox_when_configured() -> None:
    class _Sandbox:
        def __init__(self) -> None:
            self.calls = 0

        def run(self, func: Callable[..., object], *args: object, **kwargs: object) -> object:
            self.calls += 1
            return func(*args, **kwargs)

    sandbox = _Sandbox()
    frames = [pd.DataFrame({"id": [1]})]
    use_case = AssessSourceUseCase(
        _Reader(frames),
        _Profiler(),
        AssessmentSettings(chunk_size=2),
        sandbox=sandbox,
    )

    report = use_case.execute(run_id="run-1", reference="input.csv")

    assert sandbox.calls == 1
    assert report.row_count == 1
