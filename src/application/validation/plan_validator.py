"""Plan validator orchestration."""

from __future__ import annotations

from collections.abc import Sequence

from application.ports.module_registry import ModuleRegistryPort
from application.ports.plan_validator import PlanValidatorPort
from application.ports.workspace import WorkspaceProbePort
from application.validation.errors import PlanValidationError, PlanValidationErrorFactory
from application.validation.factory import build_default_checks
from application.validation.plan_check import PlanCheck
from application.validation.settings import PlanValidationSettings
from domain.entities.plan import ExecutionPlan


class PlanValidator(PlanValidatorPort):
    """Runs the configured validation checks before any step is executed."""

    def __init__(
        self,
        registry: ModuleRegistryPort,
        *,
        workspace: WorkspaceProbePort,
        max_steps: int = 100,
        max_chunk_size: int = 10_000_000,
        max_plan_bytes: int = 1_000_000,
        max_path_length: int = 260,
        max_param_depth: int = 10,
        max_string_length: int = 10_000,
        checks: Sequence[PlanCheck] | None = None,
        error_factory: PlanValidationErrorFactory | None = None,
    ) -> None:
        self._error_factory = error_factory or PlanValidationErrorFactory(module=__name__)
        settings = PlanValidationSettings(
            max_steps=max_steps,
            max_chunk_size=max_chunk_size,
            max_plan_bytes=max_plan_bytes,
            max_path_length=max_path_length,
            max_param_depth=max_param_depth,
            max_string_length=max_string_length,
        )
        self._checks = (
            tuple(checks)
            if checks is not None
            else build_default_checks(registry, settings, workspace, self._error_factory)
        )

    def validate(self, plan: ExecutionPlan) -> None:
        """Validate an already parsed domain plan."""
        if not isinstance(plan, ExecutionPlan):
            raise self._error_factory.error(
                code="PLAN_INVALID_SCHEMA",
                message="Plan must be an ExecutionPlan",
            )

        for check in self._checks:
            check.validate(plan)


__all__ = ["PlanValidationError", "PlanValidator"]
