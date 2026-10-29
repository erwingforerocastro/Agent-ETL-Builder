"""Transformation CSV log with formula-injection neutralization."""

from __future__ import annotations

import csv
import json
import sys
import threading
from pathlib import Path
from typing import TextIO

from application.logging.redaction import redact_mapping, redact_value
from application.ports.transform_log import TransformLogRow

_HEADER = (
    "ID",
    "Filename",
    "Chunk",
    "Prev_Step",
    "Step",
    "Date",
    "Result",
    "Error",
    "Warnings",
)


class CsvTransformLog:
    """Appends one row per transformation step to ``transform_log.csv``."""

    def __init__(
        self,
        *,
        artifacts_root: Path,
        stderr: TextIO | None = None,
    ) -> None:
        self._root = artifacts_root
        self._stderr = stderr or sys.stderr
        self._lock = threading.RLock()

    def append(self, row: TransformLogRow) -> None:
        safe_row = _redact_row(row)
        with self._lock:
            try:
                self._write(safe_row)
            except Exception as exc:
                self._fallback(safe_row, exc)

    def _write(self, row: TransformLogRow) -> None:
        if not _safe_run_id(row.run_id):
            raise ValueError("invalid run_id for transform log")
        directory = self._root / row.run_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "transform_log.csv"
        write_header = not path.exists() or path.stat().st_size == 0
        values = [
            row.run_id,
            row.filename,
            row.chunk,
            row.prev_step,
            row.step,
            row.date.isoformat(),
            _json_value(row.result),
            _json_value(row.error) if row.error is not None else "",
            _json_value(list(row.warnings)),
        ]
        with path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            if write_header:
                writer.writerow(_HEADER)
            writer.writerow([_safe_cell(value) for value in values])

    def _fallback(self, row: TransformLogRow, exc: Exception) -> None:
        payload = {
            "event": "transform_log_fallback",
            "error_type": type(exc).__name__,
            "run_id": row.run_id,
            "step": row.step,
            "row": {
                "filename": row.filename,
                "chunk": row.chunk,
                "prev_step": row.prev_step,
                "result": row.result,
                "error": row.error,
                "warnings": list(row.warnings),
            },
        }
        try:
            print(
                json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str),
                file=self._stderr,
            )
            self._stderr.flush()
        except Exception:
            return


def _json_value(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _safe_cell(value: object) -> str:
    text = str(value)
    if text and text[0] in {"=", "+", "-", "@", "\t", "\r"}:
        return "'" + text
    return text


def _redact_row(row: TransformLogRow) -> TransformLogRow:
    return TransformLogRow(
        run_id=row.run_id,
        filename=row.filename,
        chunk=row.chunk,
        prev_step=row.prev_step,
        step=row.step,
        date=row.date,
        result=redact_mapping(row.result),
        error=redact_mapping(row.error) if row.error is not None else None,
        warnings=tuple(str(redact_value(warning)) for warning in row.warnings),
    )


def _safe_run_id(run_id: str) -> bool:
    if run_id in {"", ".", ".."} or "\x00" in run_id:
        return False
    return Path(run_id).name == run_id


__all__ = ["CsvTransformLog"]
