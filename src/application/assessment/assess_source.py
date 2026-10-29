"""Read-only source assessment use case."""

from __future__ import annotations

from typing import cast

from application.assessment.findings import build_assessment_report
from application.assessment.models import AssessmentSettings
from application.assessment.ports import SourceProfilePort, SourceReaderPort
from application.ports.sandbox import SandboxRunnerPort
from application.profiling.models import ProfileRequest
from domain.entities.assessment import AssessmentReport


class AssessSourceUseCase:
    """Resolve a workspace source, profile it fully, and build a draft plan."""

    def __init__(
        self,
        reader: SourceReaderPort,
        profiler: SourceProfilePort,
        settings: AssessmentSettings | None = None,
        *,
        sandbox: SandboxRunnerPort | None = None,
    ) -> None:
        self._reader = reader
        self._profiler = profiler
        self._settings = settings or AssessmentSettings()
        self._sandbox = sandbox

    def execute(self, *, run_id: str, reference: str) -> AssessmentReport:
        """Run one full-source assessment without writing to a destination."""
        if self._sandbox is None:
            return self._assess(run_id=run_id, reference=reference)
        return cast(
            AssessmentReport,
            self._sandbox.run(
                self._assess,
                run_id=run_id,
                reference=reference,
            ),
        )

    def _assess(self, *, run_id: str, reference: str) -> AssessmentReport:
        source = self._reader.describe(reference)
        request = ProfileRequest(
            run_id=run_id,
            source_id=source.source_id,
            source_type=source.source_type,
            chunk_size=self._settings.chunk_size,
            content_hash=source.content_hash,
        )
        outcome = self._profiler.execute(
            self._reader.iter_chunks(source, chunk_size=self._settings.chunk_size),
            request,
        )
        return build_assessment_report(
            run_id=run_id,
            source=source,
            profile=outcome.report,
            artifacts=outcome.artifacts,
            chunk_size=self._settings.chunk_size,
        )


__all__ = ["AssessSourceUseCase"]
