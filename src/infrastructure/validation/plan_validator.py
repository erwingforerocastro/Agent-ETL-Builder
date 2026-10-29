"""Infrastructure facade for parsing and validating plans."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from application.ports.module_registry import ModuleRegistryReadPort
from application.ports.plan_sizer import PlanSizerPort
from application.ports.plan_validator import PlanValidatorPort
from application.ports.workspace import WorkspaceProbePort
from application.validation.errors import PlanValidationErrorFactory
from application.validation.plan_validation_check import PlanValidationCheck
from application.validation.plan_validator import PlanValidator as CorePlanValidator
from application.validation.settings import PlanValidationSettings
from domain.entities.plan import ExecutionPlan
from domain.errors import PlanValidationError
from infrastructure.validation.plan_schema import parse_plan


class PlanValidator(PlanValidatorPort):
    """Parses JSON-compatible plans and delegates policy checks inward."""

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
        self._validator = CorePlanValidator(
            registry,
            workspace=workspace,
            sizer=sizer,
            settings=settings,
            checks=checks,
            error_factory=self._error_factory,
        )

    def validate(self, plan: ExecutionPlan | Mapping[str, object]) -> None:
        """Validate a domain plan or a JSON-compatible plan payload."""
        if isinstance(plan, Mapping):
            plan = parse_plan(plan)
        if not isinstance(plan, ExecutionPlan):
            raise self._error_factory.error(
                code="PLAN_INVALID_SCHEMA",
                message="Plan must be an ExecutionPlan or a plan payload",
            )

        self._validator.validate(plan)


__all__ = ["PlanValidationError", "PlanValidator"]
