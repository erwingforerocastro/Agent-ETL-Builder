"""Deterministic in-memory chunk iteration."""

from __future__ import annotations

from collections.abc import Iterator

import pandas as pd

from domain.entities.ingestion import ChunkSpec, chunk_specs


def iter_frame_chunks(
    frame: pd.DataFrame,
    chunk_size: int,
) -> Iterator[tuple[ChunkSpec, pd.DataFrame]]:
    """Yield ordered, independent chunks covering the frame exactly once."""
    for spec in chunk_specs(len(frame), chunk_size):
        yield spec, frame.iloc[spec.offset : spec.offset + spec.row_count].copy()


__all__ = ["iter_frame_chunks"]
