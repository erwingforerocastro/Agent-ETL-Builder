"""Unit tests for the JSONL run log adapter."""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from pathlib import Path

from application.logging.redaction import REDACTED
from application.ports.run_log import RunLogEntry
from infrastructure.logging.jsonl import JsonlRunLog
from infrastructure.logging.run_log import InMemoryRunLog


def _entry(**overrides: object) -> RunLogEntry:
    values: dict[str, object] = {
        "timestamp": datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        "level": "info",
        "run_id": "run-1",
        "event": "step_finished",
        "status": "success",
        "step_id": "s1",
        "module": "trim_whitespace",
        "duration_ms": 12.5,
        "context": {"rows": 2, "password": "secret"},
    }
    values.update(overrides)
    return RunLogEntry(**values)  # type: ignore[arg-type]


def test_append_writes_jsonl_and_redacts(tmp_path: Path) -> None:
    memory = InMemoryRunLog()
    log = JsonlRunLog(memory, logs_root=tmp_path / "logs", stderr=io.StringIO())

    log.append(_entry())

    lines = (tmp_path / "logs" / "run-1.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["event"] == "step_finished"
    assert payload["timestamp"] == "2026-01-02T03:04:05+00:00"
    assert payload["context"] == {"rows": 2, "password": REDACTED}
    assert payload["error"] is None
    assert memory.entries("run-1")[0].context["password"] == REDACTED


def test_error_is_serialized_and_redacted(tmp_path: Path) -> None:
    memory = InMemoryRunLog()
    log = JsonlRunLog(memory, logs_root=tmp_path / "logs", stderr=io.StringIO())

    log.append(
        _entry(
            level="error",
            error={
                "code": "TRANSFORMATION_FAILED",
                "message": "failed",
                "context": {"token": "abc"},
            },
        )
    )

    payload = json.loads((tmp_path / "logs" / "run-1.jsonl").read_text(encoding="utf-8"))
    assert payload["error"]["code"] == "TRANSFORMATION_FAILED"
    assert payload["error"]["context"] == {"token": REDACTED}


def test_write_failure_falls_back_to_stderr_and_keeps_memory(tmp_path: Path) -> None:
    memory = InMemoryRunLog()
    stderr = io.StringIO()
    root = tmp_path / "logs"
    root.write_text("not a directory", encoding="utf-8")
    log = JsonlRunLog(memory, logs_root=root, stderr=stderr)

    log.append(_entry())

    assert memory.entries("run-1")
    fallback = json.loads(stderr.getvalue())
    assert fallback["event"] == "run_log_fallback"
    assert fallback["entry"]["event"] == "step_finished"


def test_invalid_run_id_falls_back_without_writing_outside(tmp_path: Path) -> None:
    memory = InMemoryRunLog()
    stderr = io.StringIO()
    log = JsonlRunLog(memory, logs_root=tmp_path / "logs", stderr=stderr)

    log.append(_entry(run_id="../escape"))

    assert not (tmp_path / "escape.jsonl").exists()
    assert "run_log_fallback" in stderr.getvalue()
    assert memory.entries("../escape")
