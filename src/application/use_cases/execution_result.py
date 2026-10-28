"""Execution result contract shared by use cases and ports."""

from dataclasses import dataclass
from typing import Any, Literal

ExecutionStatus = Literal["success", "partial", "failed"]


@dataclass(frozen=True, slots=True)
class ExecutionStepError:
    """Sanitized failure recorded for one execution step."""

    step_id: str | None
    operation: str
    error_type: str
    message: str

    def to_dict(self) -> dict[str, object]:
        return {
            "step_id": self.step_id,
            "operation": self.operation,
            "error_type": self.error_type,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class PlanExecutionResult:
    """Result of running a plan."""

    status: ExecutionStatus
    outputs: tuple[object, ...]
    data: object | None = None
    include_data: bool = False
    errors: tuple[ExecutionStepError, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": self.status,
            "outputs": list(self.outputs),
        }
        if self.include_data:
            result["dataframe"] = self.data
        if self.errors:
            result["errors"] = [error.to_dict() for error in self.errors]
        return result


__all__ = ["ExecutionStatus", "ExecutionStepError", "PlanExecutionResult"]
