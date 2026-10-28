"""Deterministic plan intake for tests and local development."""

from __future__ import annotations

import threading
from collections.abc import Sequence

from domain.entities.run import PlanIntakeResult, PlanRequest
from domain.errors import PlanValidationError


class DeterministicPlanIntake:
    """Returns preconfigured intake results in order."""

    def __init__(self, results: Sequence[PlanIntakeResult]) -> None:
        self._results = tuple(results)
        self._index = 0
        self._lock = threading.Lock()

    def request(
        self,
        request: PlanRequest,
        *,
        attempt: int,
        previous_error: PlanValidationError | None = None,
    ) -> PlanIntakeResult:
        del request, attempt, previous_error
        with self._lock:
            if self._index >= len(self._results):
                return PlanIntakeResult(reason="No deterministic plan intake result is configured")
            result = self._results[self._index]
            self._index += 1
            return result


__all__ = ["DeterministicPlanIntake"]
