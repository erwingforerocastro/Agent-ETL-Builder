"""Source identity and deterministic chunk manifest value objects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from domain.entities._validation import (
    require_non_negative_int,
    require_positive_int,
    require_text,
)

SourceType = Literal["csv", "json", "jsonl", "parquet", "postgresql"]

SOURCE_TYPES: Final[frozenset[str]] = frozenset({"csv", "json", "jsonl", "parquet", "postgresql"})
_MAX_IDENTIFIER_LENGTH: Final[int] = 128


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    """Stable identifiers and hashes for one ingested source."""

    source_id: str
    source_type: SourceType
    content_hash: str
    schema_hash: str
    row_count: int

    def __post_init__(self) -> None:
        require_text(self.source_id, "source_id")
        if len(self.source_id) > _MAX_IDENTIFIER_LENGTH:
            raise ValueError("source_id is too long")
        if self.source_type not in SOURCE_TYPES:
            raise ValueError(f"unsupported source_type: {self.source_type}")
        require_text(self.content_hash, "content_hash")
        require_text(self.schema_hash, "schema_hash")
        require_non_negative_int(self.row_count, "row_count")

    def to_dict(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "content_hash": self.content_hash,
            "schema_hash": self.schema_hash,
            "row_count": self.row_count,
        }


@dataclass(frozen=True, slots=True)
class ChunkSpec:
    """One deterministic, non-empty chunk of a source."""

    index: int
    offset: int
    row_count: int

    def __post_init__(self) -> None:
        require_non_negative_int(self.index, "chunk index")
        require_non_negative_int(self.offset, "chunk offset")
        require_positive_int(self.row_count, "chunk row_count")


def chunk_specs(total_rows: int, chunk_size: int) -> tuple[ChunkSpec, ...]:
    """Return sequential chunk specs covering every row exactly once."""
    require_non_negative_int(total_rows, "total_rows")
    require_positive_int(chunk_size, "chunk_size")
    specs: list[ChunkSpec] = []
    offset = 0
    index = 0
    while offset < total_rows:
        row_count = min(chunk_size, total_rows - offset)
        specs.append(ChunkSpec(index=index, offset=offset, row_count=row_count))
        offset += row_count
        index += 1
    return tuple(specs)


@dataclass(frozen=True, slots=True)
class ChunkManifest:
    """Reproducible description of how a source is split into chunks."""

    run_id: str
    source_id: str
    source_type: SourceType
    chunk_size: int
    total_rows: int
    chunks: tuple[ChunkSpec, ...]
    content_hash: str
    schema_hash: str
    merge_method: str = "concat"

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.run_id, "run_id"),
            (self.source_id, "source_id"),
            (self.content_hash, "content_hash"),
            (self.schema_hash, "schema_hash"),
            (self.merge_method, "merge_method"),
        ):
            require_text(value, field_name)
            if len(value) > _MAX_IDENTIFIER_LENGTH:
                raise ValueError(f"{field_name} is too long")
        if self.source_type not in SOURCE_TYPES:
            raise ValueError(f"unsupported source_type: {self.source_type}")
        require_positive_int(self.chunk_size, "chunk_size")
        require_non_negative_int(self.total_rows, "total_rows")
        object.__setattr__(self, "chunks", tuple(self.chunks))
        expected = chunk_specs(self.total_rows, self.chunk_size)
        if self.chunks != expected:
            raise ValueError("chunks must match deterministic chunking")

    @classmethod
    def from_identity(
        cls,
        *,
        run_id: str,
        identity: SourceIdentity,
        chunk_size: int,
        merge_method: str = "concat",
    ) -> ChunkManifest:
        return cls(
            run_id=run_id,
            source_id=identity.source_id,
            source_type=identity.source_type,
            chunk_size=chunk_size,
            total_rows=identity.row_count,
            chunks=chunk_specs(identity.row_count, chunk_size),
            content_hash=identity.content_hash,
            schema_hash=identity.schema_hash,
            merge_method=merge_method,
        )

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "source_id": self.source_id,
            "source_type": self.source_type,
            "chunk_size": self.chunk_size,
            "total_rows": self.total_rows,
            "chunks": [
                {
                    "index": chunk.index,
                    "offset": chunk.offset,
                    "row_count": chunk.row_count,
                }
                for chunk in self.chunks
            ],
            "content_hash": self.content_hash,
            "schema_hash": self.schema_hash,
            "merge_method": self.merge_method,
        }


__all__ = [
    "SOURCE_TYPES",
    "ChunkManifest",
    "ChunkSpec",
    "SourceIdentity",
    "SourceType",
    "chunk_specs",
]
