"""Backward-compatible interpreter facade."""

from typing import Any

from application.ports.module_registry import ModuleRegistryPort
from application.use_cases.execute_plan import (
    ExecutePlanUseCase,
    PlanExecutionError,
    PlanExecutionResult,
)
from domain.entities.plan import ExecutionPlan
from infrastructure.interpreter.step_runner import SandboxStepRunner
from infrastructure.sandbox.executor import SandboxExecutor
from infrastructure.sandbox.limits import SandboxLimits

InterpreterError = PlanExecutionError


class PlanInterpreter:
    """Facade that executes plans through the execute-plan use case."""

    def __init__(
        self,
        registry: ModuleRegistryPort,
        sandbox: SandboxExecutor | None = None,
        limits: SandboxLimits | None = None,
    ) -> None:
        runner = SandboxStepRunner(registry, sandbox=sandbox, limits=limits)
        self._use_case = ExecutePlanUseCase(runner)

    def execute(self, plan: ExecutionPlan) -> dict[str, Any]:
        result: PlanExecutionResult = self._use_case.execute(plan)
        return result.to_dict()


__all__ = ["InterpreterError", "PlanInterpreter"]
