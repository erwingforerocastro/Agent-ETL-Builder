"""Profiling and artifact-writing ports."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from application.profiling.models import ProfileArtifacts, ProfileRequest
from domain.entities.profiling import ChunkProfile, ProfileReport


class ChunkProfilerPort(Protocol):
    """Profile opaque source chunks and merge their records."""

    def profile_chunk(
        self,
        chunk: object,
        *,
        chunk_index: int,
    ) -> ChunkProfile: ...

    def merge(
        self,
        chunks: Sequence[ChunkProfile],
        *,
        request: ProfileRequest,
    ) -> ProfileReport: ...


class ProfileArtifactWriterPort(Protocol):
    """Persist chunk records, the quality CSV, and the info JSON."""

    def write_chunk(
        self,
        request: ProfileRequest,
        chunk: ChunkProfile,
    ) -> str: ...

    def write_report(self, report: ProfileReport) -> ProfileArtifacts: ...


__all__ = ["ChunkProfilerPort", "ProfileArtifactWriterPort"]
