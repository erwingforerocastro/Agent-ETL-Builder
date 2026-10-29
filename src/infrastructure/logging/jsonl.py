"""JSONL run log with in-memory reads and stderr fallback."""

from __future__ import annotations

import json
import sys
import threading
from dataclasses import replace
from pathlib import Path
from typing import TextIO

from application.logging.redaction import redact_mapping, redact_value
from application.ports.run_log import RunLogEntry, RunLogPort


class JsonlRunLog:
    """Appends structured events to ``logs/<run_id>.jsonl``."""

    def __init__(
        self,
        memory: RunLogPort,
        *,
        logs_root: Path,
        stderr: TextIO | None = None,
    ) -> None:
        self._memory = memory
        self._root = logs_root
        self._stderr = stderr or sys.stderr
        self._lock = threading.RLock()

    def append(self, entry: RunLogEntry) -> None:
        safe_entry = _redact_entry(entry)
        self._memory.append(safe_entry)
        with self._lock:
            try:
                self._write(safe_entry)
            except Exception as exc:
                self._fallback(safe_entry, exc)

    def entries(self, run_id: str) -> tuple[RunLogEntry, ...]:
        return self._memory.entries(run_id)

    def _write(self, entry: RunLogEntry) -> None:
        if not _safe_run_id(entry.run_id):
            raise ValueError("invalid run_id for log file")
        self._root.mkdir(parents=True, exist_ok=True)
        path = self._root / f"{entry.run_id}.jsonl"
        line = json.dumps(
            entry.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)
            handle.write("\n")

    def _fallback(self, entry: RunLogEntry, exc: Exception) -> None:
        payload = {
            "event": "run_log_fallback",
            "error_type": type(exc).__name__,
            "entry": entry.to_dict(),
        }
        try:
            print(
                json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str),
                file=self._stderr,
            )
            self._stderr.flush()
        except Exception:
            return


def _redact_entry(entry: RunLogEntry) -> RunLogEntry:
    message = entry.message
    if message is not None:
        message = str(redact_value(message))
    return replace(
        entry,
        message=message,
        error=redact_mapping(entry.error) if entry.error is not None else None,
        context=redact_mapping(entry.context),
    )


def _safe_run_id(run_id: str) -> bool:
    if run_id in {"", ".", ".."} or "\x00" in run_id:
        return False
    return Path(run_id).name == run_id


__all__ = ["JsonlRunLog"]
