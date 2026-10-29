"""Unit tests for deterministic chunk manifests."""

from __future__ import annotations

import pandas as pd
import pytest

from domain.entities.ingestion import (
    ChunkManifest,
    ChunkSpec,
    SourceIdentity,
    chunk_specs,
)
from infrastructure.ingestion.chunking import iter_frame_chunks
from infrastructure.ingestion.identifiers import source_identity_for_frame


def _identity(frame: pd.DataFrame) -> SourceIdentity:
    return source_identity_for_frame(
        frame,
        source_type="csv",
        canonical_uri="C:/data/input.csv",
    )


def test_chunk_specs_cover_partial_final_chunk() -> None:
    specs = chunk_specs(5, 2)

    assert specs == (
        ChunkSpec(index=0, offset=0, row_count=2),
        ChunkSpec(index=1, offset=2, row_count=2),
        ChunkSpec(index=2, offset=4, row_count=1),
    )


def test_chunk_specs_are_empty_for_empty_source() -> None:
    assert chunk_specs(0, 10) == ()


@pytest.mark.parametrize(("total_rows", "chunk_size"), [(-1, 10), (0, 0), (1, -1)])
def test_chunk_specs_reject_invalid_values(total_rows: int, chunk_size: int) -> None:
    with pytest.raises(ValueError, match=r"total_rows|chunk_size"):
        chunk_specs(total_rows, chunk_size)


def test_iter_frame_chunks_returns_independent_ordered_chunks() -> None:
    frame = pd.DataFrame({"id": [1, 2, 3, 4, 5]})

    chunks = list(iter_frame_chunks(frame, 2))

    assert [spec.index for spec, _ in chunks] == [0, 1, 2]
    assert [chunk["id"].tolist() for _, chunk in chunks] == [[1, 2], [3, 4], [5]]

    chunks[0][1].loc[0, "id"] = 99
    assert frame["id"].tolist() == [1, 2, 3, 4, 5]


def test_chunk_manifest_round_trips_to_dict() -> None:
    frame = pd.DataFrame({"id": [1, 2, 3]})
    identity = _identity(frame)

    manifest = ChunkManifest.from_identity(
        run_id="run-1",
        identity=identity,
        chunk_size=2,
    )

    assert manifest.chunk_count == 2
    assert manifest.chunks[1] == ChunkSpec(index=1, offset=2, row_count=1)
    assert manifest.to_dict() == {
        "run_id": "run-1",
        "source_id": identity.source_id,
        "source_type": "csv",
        "chunk_size": 2,
        "total_rows": 3,
        "chunks": [
            {"index": 0, "offset": 0, "row_count": 2},
            {"index": 1, "offset": 2, "row_count": 1},
        ],
        "content_hash": identity.content_hash,
        "schema_hash": identity.schema_hash,
        "merge_method": "concat",
    }


def test_chunk_manifest_rejects_non_deterministic_chunks() -> None:
    identity = _identity(pd.DataFrame({"id": [1, 2, 3]}))

    with pytest.raises(ValueError, match="deterministic"):
        ChunkManifest(
            run_id="run-1",
            source_id=identity.source_id,
            source_type="csv",
            chunk_size=2,
            total_rows=3,
            chunks=(ChunkSpec(index=0, offset=0, row_count=3),),
            content_hash=identity.content_hash,
            schema_hash=identity.schema_hash,
        )


def test_source_identity_rejects_invalid_source_type() -> None:
    with pytest.raises(ValueError, match="unsupported source_type"):
        SourceIdentity(
            source_id="src_1",
            source_type="xml",  # type: ignore[arg-type]
            content_hash="sha256:a",
            schema_hash="sha256:b",
            row_count=1,
        )


def test_source_identity_rejects_overlong_identifiers() -> None:
    with pytest.raises(ValueError, match="source_id is too long"):
        SourceIdentity(
            source_id="src_" + "a" * 200,
            source_type="csv",
            content_hash="sha256:a",
            schema_hash="sha256:b",
            row_count=1,
        )


def test_chunk_manifest_rejects_invalid_source_type() -> None:
    identity = _identity(pd.DataFrame({"id": [1]}))

    with pytest.raises(ValueError, match="unsupported source_type"):
        ChunkManifest(
            run_id="run-1",
            source_id=identity.source_id,
            source_type="xml",  # type: ignore[arg-type]
            chunk_size=1,
            total_rows=1,
            chunks=(ChunkSpec(index=0, offset=0, row_count=1),),
            content_hash=identity.content_hash,
            schema_hash=identity.schema_hash,
        )


def test_chunk_manifest_rejects_overlong_run_id() -> None:
    identity = _identity(pd.DataFrame({"id": [1]}))

    with pytest.raises(ValueError, match="run_id is too long"):
        ChunkManifest.from_identity(
            run_id="r" * 200,
            identity=identity,
            chunk_size=1,
        )


def test_chunk_spec_rejects_empty_chunk() -> None:
    with pytest.raises(ValueError, match="chunk row_count"):
        ChunkSpec(index=0, offset=0, row_count=0)
