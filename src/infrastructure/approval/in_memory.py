"""In-memory human approval gateway."""

from __future__ import annotations

import threading

from application.ports.cancellation import CancellationTokenPort
from application.ports.clock import ClockPort
from domain.entities.run import ApprovalState
from infrastructure.clock import SystemClock


class InMemoryApprovalGateway:
    """Waits for an in-process approval decision with a bounded timeout."""

    _CANCELLATION_POLL_SECONDS = 0.05

    def __init__(self, clock: ClockPort | None = None) -> None:
        self._clock = clock or SystemClock()
        self._condition = threading.Condition()
        self._decisions: dict[str, ApprovalState] = {}

    def request(
        self,
        run_id: str,
        *,
        timeout_seconds: float,
        cancellation: CancellationTokenPort,
    ) -> ApprovalState:
        deadline = self._clock.monotonic() + timeout_seconds
        with self._condition:
            while True:
                if cancellation.is_cancelled():
                    return ApprovalState.CANCELLED
                decision = self._decisions.get(run_id)
                if decision is not None:
                    return decision
                remaining = deadline - self._clock.monotonic()
                if remaining <= 0:
                    return ApprovalState.TIMED_OUT
                self._condition.wait(min(remaining, self._CANCELLATION_POLL_SECONDS))

    def decide(self, run_id: str, decision: ApprovalState) -> None:
        if decision not in {ApprovalState.APPROVED, ApprovalState.REJECTED}:
            raise ValueError("approval decisions must be approved or rejected")
        with self._condition:
            self._decisions[run_id] = decision
            self._condition.notify_all()


__all__ = ["InMemoryApprovalGateway"]
