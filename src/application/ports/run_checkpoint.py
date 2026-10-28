"""Checkpoint contract for workflow runs."""

from typing import Protocol

from domain.entities.run import Run


class RunCheckpointPort(Protocol):
    def save(self, run: Run) -> None: ...

    def get(self, run_id: str) -> Run | None: ...
