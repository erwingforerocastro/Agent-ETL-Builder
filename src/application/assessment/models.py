"""Application models for read-only source assessment."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from domain.entities._validation import require_positive_int, require_text
from domain.entities.ingestion import SOURCE_TYPES, SourceType


@dataclass(frozen=True, slots=True)
class AssessmentSettings:
    """Bounded v1 settings for one full-source assessment."""

    chunk_size: int = 10_000

    def __post_init__(self) -> None:
        require_positive_int(self.chunk_size, "chunk_size")


@dataclass(frozen=True, slots=True)
class SourceDescriptor:
    """Resolved source metadata used by assessment and draft plans."""

    source_id: str
    source_type: SourceType
    operation: str
    params: Mapping[str, object]
    path: str
    content_hash: str

    def __post_init__(self) -> None:
        require_text(self.source_id, "source_id")
        if self.source_type not in SOURCE_TYPES:
            raise ValueError(f"unsupported source_type: {self.source_type}")
        require_text(self.operation, "operation")
        require_text(self.path, "path")
        require_text(self.content_hash, "content_hash")
        object.__setattr__(self, "params", dict(self.params))


__all__ = ["AssessmentSettings", "SourceDescriptor"]
