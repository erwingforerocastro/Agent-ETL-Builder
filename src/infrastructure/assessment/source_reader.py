"""Workspace-confined source resolution and chunk iteration."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from typing import Final

from application.assessment.models import SourceDescriptor
from application.ports.workspace import WorkspaceProbePort
from application.validation.path_validator import PathValueValidator
from application.validation.settings import PlanValidationSettings
from domain.entities.ingestion import SourceType
from domain.errors import IngestionError, PlanValidationError
from infrastructure.ingestion.csv import iter_csv_chunks
from infrastructure.ingestion.identifiers import (
    canonical_file_uri,
    file_content_hash,
    source_id_for,
)
from infrastructure.ingestion.json import iter_json_chunks, iter_jsonl_chunks
from infrastructure.ingestion.parquet import iter_parquet_chunks

_SOURCE_READERS: Final[dict[str, tuple[SourceType, str]]] = {
    ".csv": ("csv", "read_csv"),
    ".json": ("json", "read_json"),
    ".jsonl": ("jsonl", "read_jsonl"),
    ".ndjson": ("jsonl", "read_jsonl"),
    ".parquet": ("parquet", "read_parquet"),
    ".pq": ("parquet", "read_parquet"),
}


class WorkspaceSourceReader:
    """Resolves workspace files and streams them through v1 readers."""

    def __init__(
        self,
        probe: WorkspaceProbePort,
        *,
        settings: PlanValidationSettings | None = None,
    ) -> None:
        self._probe = probe
        self._path_validator = PathValueValidator(
            settings or PlanValidationSettings(),
            probe,
        )

    def describe(self, reference: str) -> SourceDescriptor:
        """Resolve a safe workspace-relative file reference."""
        text = reference.strip() if isinstance(reference, str) else ""
        if not text:
            raise _source_error(
                code="SOURCE_REFERENCE_INVALID",
                message="Source reference must not be blank",
            )
        parts = tuple(PurePosixPath(text.replace("\\", "/")).parts)
        try:
            self._path_validator.validate(text, label="source")
        except PlanValidationError as exc:
            raise _source_error(
                code="SOURCE_REFERENCE_INVALID",
                message="Source reference is not a safe workspace path",
                context={"reason": exc.code},
            ) from exc
        info = self._probe.inspect(parts)
        if info.error is not None or info.symlink:
            raise _source_error(
                code="SOURCE_REFERENCE_INVALID",
                message="Source reference is not a safe workspace path",
            )
        path = Path(info.resolved)
        try:
            if not path.exists():
                raise _source_error(
                    code="SOURCE_NOT_FOUND",
                    message="Source file was not found",
                )
            if not path.is_file():
                raise _source_error(
                    code="SOURCE_NOT_FILE",
                    message="Source reference must name a file",
                )
        except OSError as exc:
            raise _source_error(
                code="SOURCE_INSPECTION_FAILED",
                message="Source could not be inspected",
            ) from exc

        reader = _SOURCE_READERS.get(path.suffix.lower())
        if reader is None:
            raise _source_error(
                code="SOURCE_UNSUPPORTED_TYPE",
                message="Source file type is not supported",
                context={"suffix": path.suffix.lower()},
            )
        source_type, operation = reader
        return SourceDescriptor(
            source_id=source_id_for(source_type, canonical_file_uri(path)),
            source_type=source_type,
            operation=operation,
            params={"path": PurePosixPath(*parts).as_posix()},
            path=str(path),
            content_hash=file_content_hash(path),
        )

    def iter_chunks(
        self,
        source: SourceDescriptor,
        *,
        chunk_size: int,
    ) -> Iterator[object]:
        """Yield source chunks using the reader selected by source type."""
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        path = source.path
        if source.source_type == "csv":
            yield from iter_csv_chunks(path=path, chunk_size=chunk_size)
            return
        if source.source_type == "json":
            yield from iter_json_chunks(path=path, chunk_size=chunk_size)
            return
        if source.source_type == "jsonl":
            yield from iter_jsonl_chunks(path=path, chunk_size=chunk_size)
            return
        if source.source_type == "parquet":
            yield from iter_parquet_chunks(path=path, chunk_size=chunk_size)
            return
        raise _source_error(
            code="SOURCE_UNSUPPORTED_TYPE",
            message="Source type is not supported",
            context={"source_type": source.source_type},
        )


def _source_error(
    *,
    code: str,
    message: str,
    context: dict[str, object] | None = None,
) -> IngestionError:
    return IngestionError(
        code=code,
        message=message,
        module=__name__,
        context=context,
    )


__all__ = ["WorkspaceSourceReader"]
