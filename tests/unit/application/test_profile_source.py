"""Unit tests for profiling orchestration."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

import pytest

from application.profiling.models import (
    ProfileArtifacts,
    ProfileLimits,
    ProfileRequest,
    ProfileThresholds,
)
from application.use_cases.profile_source import ProfileSourceUseCase
from domain.entities.profiling import ChunkProfile, ProfileReport, ProfileScope


class _FakeProfiler:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []
        self.merged: list[ChunkProfile] = []
        self.request: ProfileRequest | None = None

    def profile_chunk(
        self,
        chunk: object,
        *,
        chunk_index: int,
        request: ProfileRequest,
    ) -> ChunkProfile:
        self.calls.append((chunk_index, str(chunk)))
        assert request.chunk_size > 0
        return ChunkProfile(
            chunk_index=chunk_index,
            row_count=1,
            complete_rows=1,
            columns=(),
        )

    def merge(
        self,
        chunks: Sequence[ChunkProfile],
        *,
        request: ProfileRequest,
    ) -> ProfileReport:
        self.merged = list(chunks)
        self.request = request
        return ProfileReport(
            run_id=request.run_id,
            source_id=request.source_id,
            source_type=request.source_type,
            row_count=len(chunks),
            chunk_count=len(chunks),
            chunk_size=request.chunk_size,
            scope=request.scope,
            method=request.method,
            merge_method=request.merge_method,
            approximate=request.approximate,
            columns=(),
            metrics=(),
        )


class _FakeWriter:
    def __init__(self) -> None:
        self.chunks: list[int] = []
        self.report: ProfileReport | None = None
        self.events: list[str] | None = None

    def write_chunk(self, request: ProfileRequest, chunk: ChunkProfile) -> str:
        del request
        self.chunks.append(chunk.chunk_index)
        if self.events is not None:
            self.events.append(f"write:{chunk.chunk_index}")
        return f"chunk-{chunk.chunk_index}.json"

    def write_report(self, report: ProfileReport) -> ProfileArtifacts:
        self.report = report
        if self.events is not None:
            self.events.append("report")
        return ProfileArtifacts(
            quality_path="quality.csv",
            info_path="info.json",
            chunk_paths=tuple(f"chunk-{index}.json" for index in range(report.chunk_count)),
        )


def _request() -> ProfileRequest:
    return ProfileRequest(
        run_id="run-1",
        source_id="src_abc",
        source_type="csv",
        scope=ProfileScope.FULL,
        chunk_size=2,
        thresholds=ProfileThresholds(),
        limits=ProfileLimits(),
    )


def test_profiles_each_chunk_before_merging_and_writing() -> None:
    profiler = _FakeProfiler()
    writer = _FakeWriter()
    events: list[str] = []
    profiler_calls = profiler.calls
    writer.events = events
    original_profile = profiler.profile_chunk

    def profile(chunk: object, *, chunk_index: int, request: ProfileRequest) -> ChunkProfile:
        events.append(f"profile:{chunk_index}")
        return original_profile(chunk, chunk_index=chunk_index, request=request)

    profiler.profile_chunk = profile  # type: ignore[method-assign]
    use_case = ProfileSourceUseCase(profiler, writer)

    outcome = use_case.execute(["first", "second"], _request())

    assert profiler_calls == [(0, "first"), (1, "second")]
    assert writer.chunks == [0, 1]
    assert [record.chunk_index for record in profiler.merged] == [0, 1]
    assert [record.metric for record in outcome.report.metrics] == []
    assert writer.report is outcome.report
    assert outcome.artifacts.quality_path == "quality.csv"
    assert events == ["profile:0", "write:0", "profile:1", "write:1", "report"]


def test_empty_chunk_stream_still_writes_a_report() -> None:
    profiler = _FakeProfiler()
    writer = _FakeWriter()

    outcome = ProfileSourceUseCase(profiler, writer).execute([], _request())

    assert outcome.report.chunk_count == 0
    assert writer.chunks == []
    assert writer.report is outcome.report


def test_profiler_failure_stops_writing() -> None:
    class FailingProfiler(_FakeProfiler):
        def profile_chunk(
            self,
            chunk: object,
            *,
            chunk_index: int,
            request: ProfileRequest,
        ) -> ChunkProfile:
            del chunk, chunk_index, request
            raise RuntimeError("boom")

    writer = _FakeWriter()

    with pytest.raises(RuntimeError, match="boom"):
        ProfileSourceUseCase(FailingProfiler(), writer).execute(["bad"], _request())

    assert writer.chunks == []
    assert writer.report is None


def test_request_rejects_invalid_profiling_policy() -> None:
    with pytest.raises(ValueError, match="sample profiles"):
        replace(_request(), scope=ProfileScope.SAMPLE)
    with pytest.raises(ValueError, match="rules"):
        replace(_request(), rules=(object(),))  # type: ignore[arg-type]
