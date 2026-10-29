"""Outcome returned by run workflow operations."""

from dataclasses import dataclass

from application.ports.cleanup import CleanupResult
from application.use_cases.execution_result import PlanExecutionResult
from domain.entities.run import Run


@dataclass(frozen=True, slots=True)
class RunOutcome:
    """The checkpointed run plus optional execution and cleanup results."""

    run: Run
    result: PlanExecutionResult | None = None
    cleanup: CleanupResult | None = None


__all__ = ["RunOutcome"]
