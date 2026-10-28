"""Infrastructure facade for parsing and validating plans."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from application.ports.module_registry import ModuleRegistryPort
from application.ports.plan_validator import PlanValidatorPort
from application.validation.errors import PlanValidationErrorFactory
from application.validation.plan_check import PlanCheck
from application.validation.plan_validator import PlanValidator as CorePlanValidator
from domain.entities.plan import ExecutionPlan
from domain.errors import PlanValidationError
from infrastructure.validation.path_probe import FilesystemWorkspaceProbe
from infrastructure.validation.plan_schema import parse_plan


class PlanValidator(PlanValidatorPort):
    """Parses JSON-compatible plans and delegates policy checks inward."""

    def __init__(
        self,
        registry: ModuleRegistryPort,
        *,
        workspace_root: Path | str | None = None,
        max_steps: int = 100,
        max_chunk_size: int = 10_000_000,
        max_plan_bytes: int = 1_000_000,
        max_path_length: int = 260,
        max_param_depth: int = 10,
        max_string_length: int = 10_000,
        checks: Sequence[PlanCheck] | None = None,
        error_factory: PlanValidationErrorFactory | None = None,
    ) -> None:
        root = Path(workspace_root) if workspace_root is not None else Path.cwd()
        self._error_factory = error_factory or PlanValidationErrorFactory(module=__name__)
        self._validator = CorePlanValidator(
            registry,
            workspace=FilesystemWorkspaceProbe(root),
            max_steps=max_steps,
            max_chunk_size=max_chunk_size,
            max_plan_bytes=max_plan_bytes,
            max_path_length=max_path_length,
            max_param_depth=max_param_depth,
            max_string_length=max_string_length,
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
