"""Plan validator orchestration."""

from __future__ import annotations

from collections.abc import Sequence

from application.ports.module_registry import ModuleRegistryReadPort
from application.ports.plan_sizer import PlanSizerPort
from application.ports.plan_validator import PlanValidatorPort
from application.ports.workspace import WorkspaceProbePort
from application.validation.errors import PlanValidationError, PlanValidationErrorFactory
from application.validation.factory import build_default_checks
from application.validation.plan_validation_check import PlanValidationCheck
from application.validation.settings import PlanValidationSettings
from domain.entities.plan import ExecutionPlan


class PlanValidator(PlanValidatorPort):
    """Runs the configured validation checks before any step is executed."""

    def __init__(
        self,
        registry: ModuleRegistryReadPort,
        *,
        workspace: WorkspaceProbePort,
        sizer: PlanSizerPort | None = None,
        settings: PlanValidationSettings | None = None,
        checks: Sequence[PlanValidationCheck] | None = None,
        error_factory: PlanValidationErrorFactory | None = None,
    ) -> None:
        self._error_factory = error_factory or PlanValidationErrorFactory(module=__name__)
        validation_settings = settings or PlanValidationSettings()
        if checks is not None:
            self._checks = tuple(checks)
        else:
            if sizer is None:
                raise TypeError("sizer is required when checks are not provided")
            self._checks = build_default_checks(
                registry,
                validation_settings,
                workspace,
                sizer,
                self._error_factory,
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
