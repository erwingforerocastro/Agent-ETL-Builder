"""In-memory human approval gateway."""

from __future__ import annotations

import threading

from application.ports.cancellation import CancellationTokenPort
from application.ports.clock import ClockPort
from domain.entities.run import ApprovalState
from infrastructure.clock import SystemClock


class InMemoryApprovalGateway:
    """Waits for an in-process approval decision with a bounded timeout."""

    def __init__(self, clock: ClockPort | None = None) -> None:
        self._clock = clock or SystemClock()
        self._lock = threading.RLock()
        self._decisions: dict[str, ApprovalState] = {}
        self._events: dict[str, threading.Event] = {}

    def request(
        self,
        run_id: str,
        *,
        timeout_seconds: float,
        cancellation: CancellationTokenPort,
    ) -> ApprovalState:
        deadline = self._clock.monotonic() + timeout_seconds
        while True:
            if cancellation.is_cancelled():
                return ApprovalState.CANCELLED

            with self._lock:
                decision = self._decisions.get(run_id)
                event = self._events.setdefault(run_id, threading.Event())

            if decision is not None:
                return decision

            remaining = deadline - self._clock.monotonic()
            if remaining <= 0:
                return ApprovalState.TIMED_OUT
            event.wait(min(remaining, 0.05))

    def decide(self, run_id: str, decision: ApprovalState) -> None:
        if decision not in {ApprovalState.APPROVED, ApprovalState.REJECTED}:
            raise ValueError("approval decisions must be approved or rejected")
        with self._lock:
            self._decisions[run_id] = decision
            self._events.setdefault(run_id, threading.Event()).set()


__all__ = ["InMemoryApprovalGateway"]
