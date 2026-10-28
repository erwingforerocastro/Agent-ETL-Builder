"""Human approval contract."""

from typing import Protocol

from application.ports.cancellation import CancellationTokenPort
from domain.entities.run import ApprovalState


class ApprovalPort(Protocol):
    def request(
        self,
        run_id: str,
        *,
        timeout_seconds: float,
        cancellation: CancellationTokenPort,
    ) -> ApprovalState: ...

    def decide(self, run_id: str, decision: ApprovalState) -> None: ...
