"""Validated-plan execution contract used by the workflow."""

from typing import Protocol

from application.ports.cancellation import CancellationTokenPort
from application.use_cases.execution_result import PlanExecutionResult
from domain.entities.plan import ExecutionPlan


class ExecutionPort(Protocol):
    def execute(
        self,
        plan: ExecutionPlan,
        *,
        cancellation: CancellationTokenPort | None = None,
    ) -> PlanExecutionResult: ...
