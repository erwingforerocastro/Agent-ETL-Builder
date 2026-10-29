"""Atomic filesystem artifacts for profiling results."""

from __future__ import annotations

import contextlib
import csv
import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TextIO

from application.profiling.models import ProfileArtifacts, ProfileRequest
from domain.entities.profiling import ChunkProfile, MetricResult, ProfileReport
from domain.errors import ProfilingError, SandboxError
from infrastructure.profiling.paths import safe_component

_QUALITY_HEADERS: tuple[str, ...] = (
    "run_id",
    "source_id",
    "source_type",
    "chunk_merge_method",
    "metric_definition_version",
    "metric",
    "scope",
    "subject",
    "numerator",
    "denominator",
    "value",
    "threshold",
    "status",
    "approximate",
    "formula",
    "details",
)


class FilesystemProfileWriter:
    """Writes profiling artifacts below ``artifacts/<run_id>``."""

    def __init__(self, artifacts_root: Path) -> None:
        self._root = artifacts_root.resolve()

    def write_chunk(self, request: ProfileRequest, chunk: ChunkProfile) -> str:
        path = self._chunk_path(
            request.run_id,
            request.source_id,
            request.source_type,
            chunk.chunk_index,
        )
        payload = {
            "run_id": request.run_id,
            "source_id": request.source_id,
            "source_type": request.source_type,
            "profile": chunk.to_dict(),
        }
        self._write_json(path, payload)
        return str(path)

    def write_report(self, report: ProfileReport) -> ProfileArtifacts:
        run_dir = self._run_dir(report.run_id)
        source_id = safe_component(report.source_id, "source_id")
        source_type = safe_component(report.source_type, "source_type")
        prefix = f"{source_id}_{source_type}"
        quality_path = run_dir / f"{prefix}_quality.csv"
        info_path = run_dir / f"{prefix}_info.json"
        self._write_quality(quality_path, report)
        self._write_json(info_path, report.to_info_dict())
        chunk_paths = tuple(
            str(
                self._chunk_path(
                    report.run_id,
                    source_id,
                    source_type,
                    index,
                )
            )
            for index in range(report.chunk_count)
        )
        return ProfileArtifacts(
            quality_path=str(quality_path),
            info_path=str(info_path),
            chunk_paths=chunk_paths,
        )

    def _run_dir(self, run_id: str) -> Path:
        return self._root / safe_component(run_id, "run_id")

    def _chunk_path(
        self,
        run_id: str,
        source_id: str,
        source_type: str,
        chunk_index: int,
    ) -> Path:
        prefix = (
            f"{safe_component(source_id, 'source_id')}_{safe_component(source_type, 'source_type')}"
        )
        return self._run_dir(run_id) / f"{prefix}_profile_chunk_{chunk_index:06d}.json"

    def _write_quality(self, path: Path, report: ProfileReport) -> None:
        def write(handle: TextIO) -> None:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(_QUALITY_HEADERS)
            for metric in report.metrics:
                writer.writerow(_quality_row(report, metric))

        self._atomic_text(path, write)

    def _write_json(self, path: Path, payload: object) -> None:
        def write(handle: TextIO) -> None:
            json.dump(
                payload,
                handle,
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
                sort_keys=True,
            )
            handle.write("\n")

        self._atomic_text(path, write)

    def _atomic_text(self, path: Path, write: Callable[[TextIO], None]) -> None:
        temporary: str | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(
                prefix=f".{path.name}.",
                suffix=".tmp",
                dir=path.parent,
            )
            with os.fdopen(
                descriptor,
                "w",
                encoding="utf-8",
                newline="",
            ) as handle:
                write(handle)
            os.replace(temporary, path)
        except SandboxError:
            raise
        except Exception as exc:
            if temporary is not None:
                with contextlib.suppress(OSError):
                    Path(temporary).unlink(missing_ok=True)
            raise ProfilingError(
                code="PROFILE_ARTIFACT_WRITE_FAILED",
                message="Profiling artifact could not be written",
                module=__name__,
                context={"path": str(path), "error_type": type(exc).__name__},
            ) from exc


def _quality_row(report: ProfileReport, metric: MetricResult) -> tuple[str, ...]:
    details = json.dumps(
        dict(metric.details),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return (
        _csv_text(report.run_id),
        _csv_text(report.source_id),
        _csv_text(report.source_type),
        _csv_text(report.merge_method),
        _csv_text(report.metric_definition_version),
        _csv_text(metric.metric),
        _csv_text(metric.scope.value),
        _csv_text(metric.subject),
        _csv_number(metric.numerator),
        _csv_number(metric.denominator),
        _csv_number(metric.value),
        _csv_number(metric.threshold),
        _csv_text(metric.status.value),
        "true" if metric.approximate else "false",
        _csv_text(metric.formula),
        _csv_text(details),
    )


def _csv_number(value: float | int | None) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, int):
        return str(value)
    return format(value, ".12g")


def _csv_text(value: str) -> str:
    if value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return f"'{value}"
    return value


__all__ = ["FilesystemProfileWriter"]
