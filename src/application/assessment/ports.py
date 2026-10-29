"""Ports used by source assessment."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Protocol

from application.assessment.models import SourceDescriptor
from application.profiling.models import ProfileOutcome, ProfileRequest


class SourceReaderPort(Protocol):
    """Resolve a workspace source and stream its ordered chunks."""

    def describe(self, reference: str) -> SourceDescriptor: ...

    def iter_chunks(
        self,
        source: SourceDescriptor,
        *,
        chunk_size: int,
    ) -> Iterator[object]: ...


class SourceProfilePort(Protocol):
    """Profile an ordered chunk stream and persist its artifacts."""

    def execute(
        self,
        chunks: Iterable[object],
        request: ProfileRequest,
    ) -> ProfileOutcome: ...


__all__ = ["SourceProfilePort", "SourceReaderPort"]
