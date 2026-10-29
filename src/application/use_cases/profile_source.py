"""Read-only profiling orchestration and artifact persistence."""

from __future__ import annotations

from collections.abc import Iterable

from application.ports.profiling import ChunkProfilerPort, ProfileArtifactWriterPort
from application.profiling.models import ProfileOutcome, ProfileRequest


class ProfileSourceUseCase:
    """Profiles ordered chunks, saves each record, then merges and writes."""

    def __init__(
        self,
        profiler: ChunkProfilerPort,
        writer: ProfileArtifactWriterPort,
    ) -> None:
        self._profiler = profiler
        self._writer = writer

    def execute(
        self,
        chunks: Iterable[object],
        request: ProfileRequest,
    ) -> ProfileOutcome:
        records = []
        for index, chunk in enumerate(chunks):
            record = self._profiler.profile_chunk(
                chunk,
                chunk_index=index,
                request=request,
            )
            self._writer.write_chunk(request, record)
            records.append(record)

        report = self._profiler.merge(records, request=request)
        artifacts = self._writer.write_report(report)
        return ProfileOutcome(report=report, artifacts=artifacts)


__all__ = ["ProfileSourceUseCase"]
