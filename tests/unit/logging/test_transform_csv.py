"""Unit tests for the transformation CSV log adapter."""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from pathlib import Path

from application.logging.redaction import REDACTED
from application.ports.transform_log import TransformLogRow
from infrastructure.logging.transform_csv import CsvTransformLog


def _row(**overrides: object) -> TransformLogRow:
    values: dict[str, object] = {
        "run_id": "run-1",
        "filename": "output.csv",
        "chunk": "",
        "prev_step": "",
        "step": "s1",
        "date": datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        "result": {"status": "success", "rows_in": 2, "rows_out": 1},
        "error": None,
        "warnings": (),
    }
    values.update(overrides)
    return TransformLogRow(**values)  # type: ignore[arg-type]


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_append_writes_header_and_structured_values(tmp_path: Path) -> None:
    log = CsvTransformLog(artifacts_root=tmp_path, stderr=io.StringIO())

    log.append(_row())
    log.append(_row(step="s2", prev_step="s1", warnings=("empty result",)))

    path = tmp_path / "run-1" / "transform_log.csv"
    rows = _read_rows(path)
    assert len(rows) == 2
    assert rows[0]["ID"] == "run-1"
    assert rows[0]["Filename"] == "output.csv"
    assert rows[0]["Step"] == "s1"
    assert rows[0]["Date"] == "2026-01-02T03:04:05+00:00"
    assert json.loads(rows[0]["Result"]) == {
        "status": "success",
        "rows_in": 2,
        "rows_out": 1,
    }
    assert rows[0]["Error"] == ""
    assert json.loads(rows[1]["Warnings"]) == ["empty result"]


def test_error_is_json_encoded(tmp_path: Path) -> None:
    log = CsvTransformLog(artifacts_root=tmp_path, stderr=io.StringIO())

    log.append(
        _row(
            result={"status": "failed"},
            error={"code": "TRANSFORMATION_FAILED", "message": "failed"},
        )
    )

    rows = _read_rows(tmp_path / "run-1" / "transform_log.csv")
    assert json.loads(rows[0]["Error"]) == {
        "code": "TRANSFORMATION_FAILED",
        "message": "failed",
    }


def test_formula_like_cells_are_neutralized(tmp_path: Path) -> None:
    log = CsvTransformLog(artifacts_root=tmp_path, stderr=io.StringIO())

    log.append(_row(filename="=cmd", step="+step", chunk="@chunk", prev_step="-prev"))

    rows = _read_rows(tmp_path / "run-1" / "transform_log.csv")
    assert rows[0]["Filename"] == "'=cmd"
    assert rows[0]["Step"] == "'+step"
    assert rows[0]["Chunk"] == "'@chunk"
    assert rows[0]["Prev_Step"] == "'-prev"


def test_secrets_in_result_and_error_are_redacted(tmp_path: Path) -> None:
    log = CsvTransformLog(artifacts_root=tmp_path, stderr=io.StringIO())

    log.append(
        _row(
            result={"password": "secret", "status": "success"},
            error={"token": "abc", "message": "failed"},
            warnings=("password=secret",),
        )
    )

    rows = _read_rows(tmp_path / "run-1" / "transform_log.csv")
    assert json.loads(rows[0]["Result"])["password"] == REDACTED
    assert json.loads(rows[0]["Error"])["token"] == REDACTED
    assert json.loads(rows[0]["Warnings"]) == ["password=[REDACTED]"]


def test_write_failure_falls_back_to_stderr(tmp_path: Path) -> None:
    stderr = io.StringIO()
    root = tmp_path / "artifacts"
    root.write_text("not a directory", encoding="utf-8")
    log = CsvTransformLog(artifacts_root=root, stderr=stderr)

    log.append(_row())

    fallback = json.loads(stderr.getvalue())
    assert fallback["event"] == "transform_log_fallback"
    assert fallback["run_id"] == "run-1"


def test_invalid_run_id_does_not_write_outside(tmp_path: Path) -> None:
    stderr = io.StringIO()
    log = CsvTransformLog(artifacts_root=tmp_path, stderr=stderr)

    log.append(_row(run_id="../escape"))

    assert not (tmp_path.parent / "escape").exists()
    assert "transform_log_fallback" in stderr.getvalue()
