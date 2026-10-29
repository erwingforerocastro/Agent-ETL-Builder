"""Application-level profiling request and result models."""

from __future__ import annotations

from dataclasses import dataclass

from domain.entities._validation import require_positive_int, require_text
from domain.entities.ingestion import SOURCE_TYPES, SourceType
from domain.entities.profiling import ProfileReport


@dataclass(frozen=True, slots=True)
class ProfileLimits:
    """Bounded tracking for v1 profiling maps."""

    max_tracked_values: int = 100_000
    max_frequency_rows: int = 100

    def __post_init__(self) -> None:
        require_positive_int(self.max_tracked_values, "max_tracked_values")
        require_positive_int(self.max_frequency_rows, "max_frequency_rows")


@dataclass(frozen=True, slots=True)
class ProfileRequest:
    """Source identity and chunk metadata for a full-source profile."""

    run_id: str
    source_id: str
    source_type: SourceType
    chunk_size: int = 10_000
    content_hash: str | None = None

    def __post_init__(self) -> None:
        require_text(self.run_id, "run_id")
        require_text(self.source_id, "source_id")
        if self.source_type not in SOURCE_TYPES:
            raise ValueError(f"unsupported source_type: {self.source_type}")
        require_positive_int(self.chunk_size, "chunk_size")
        if self.content_hash is not None and not self.content_hash.strip():
            raise ValueError("content_hash must not be blank when provided")


@dataclass(frozen=True, slots=True)
class ProfileArtifacts:
    """Paths written for one profiling run."""

    quality_path: str
    info_path: str
    chunk_paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProfileOutcome:
    """Merged report plus written artifact locations."""

    report: ProfileReport
    artifacts: ProfileArtifacts


__all__ = [
    "ProfileArtifacts",
    "ProfileLimits",
    "ProfileOutcome",
    "ProfileRequest",
]
