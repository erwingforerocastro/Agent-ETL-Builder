"""Bounded source schema probe for natural-language planning."""

from __future__ import annotations

from application.planning.models import SourceSchema
from application.ports.source_schema import SourceSchemaPort
from infrastructure.assessment.source_reader import WorkspaceSourceReader


class WorkspaceSourceSchemaProbe(SourceSchemaPort):
    """Reads a bounded first chunk to expose column names and dtypes."""

    def __init__(self, reader: WorkspaceSourceReader, *, sample_rows: int = 50) -> None:
        if sample_rows <= 0:
            raise ValueError("sample_rows must be positive")
        self._reader = reader
        self._sample_rows = sample_rows

    def inspect(self, source: str) -> SourceSchema:
        descriptor = self._reader.describe(source)
        chunk = next(
            self._reader.iter_chunks(descriptor, chunk_size=self._sample_rows),
            None,
        )
        if chunk is None:
            return SourceSchema()
        columns = tuple(str(column) for column in getattr(chunk, "columns", ()))
        dtypes = tuple(str(dtype) for dtype in getattr(chunk, "dtypes", ()))
        return SourceSchema(columns=columns, dtypes=dtypes)


__all__ = ["WorkspaceSourceSchemaProbe"]
