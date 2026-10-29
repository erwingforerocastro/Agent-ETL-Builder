"""Factory that assembles one run workflow from shared adapters."""

from __future__ import annotations

from application.ports.approval import ApprovalPort
from application.ports.cancellation import CancellationTokenPort
from application.ports.cleanup import CleanupPort
from application.ports.clock import ClockPort
from application.ports.execution import ExecutionPort
from application.ports.module_registry import ModuleRegistryReadPort
from application.ports.plan_hasher import PlanHasherPort
from application.ports.plan_intake import PlanIntakePort
from application.ports.plan_validator import PlanValidatorPort
from application.ports.run_checkpoint import RunCheckpointPort
from application.use_cases.run_workflow import RunWorkflow
from domain.entities.run import WorkflowLimits


class RunWorkflowFactory:
    """Creates one isolated RunWorkflow instance per run."""

    def __init__(
        self,
        *,
        validator: PlanValidatorPort,
        executor: ExecutionPort,
        registry: ModuleRegistryReadPort,
        checkpoints: RunCheckpointPort,
        clock: ClockPort,
        approvals: ApprovalPort,
        cleanup: CleanupPort,
        hasher: PlanHasherPort,
        limits: WorkflowLimits,
    ) -> None:
        self._validator = validator
        self._executor = executor
        self._registry = registry
        self._checkpoints = checkpoints
        self._clock = clock
        self._approvals = approvals
        self._cleanup = cleanup
        self._hasher = hasher
        self._limits = limits

    def create(
        self,
        *,
        intake: PlanIntakePort,
        cancellation: CancellationTokenPort,
    ) -> RunWorkflow:
        return RunWorkflow(
            intake=intake,
            validator=self._validator,
            executor=self._executor,
            registry=self._registry,
            checkpoints=self._checkpoints,
            clock=self._clock,
            approvals=self._approvals,
            cleanup=self._cleanup,
            hasher=self._hasher,
            cancellation=cancellation,
            limits=self._limits,
        )


__all__ = ["RunWorkflowFactory"]
