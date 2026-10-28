"""Plan validator orchestration."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from application.ports.module_registry import ModuleRegistryPort
from application.ports.plan_validator import PlanValidatorPort
from domain.entities.plan import ExecutionPlan
from infrastructure.validation.errors import (
    PlanValidationError,
    PlanValidationErrorFactory,
)
from infrastructure.validation.factory import build_default_checks
from infrastructure.validation.plan_check import PlanCheck
from infrastructure.validation.plan_schema import parse_plan
from infrastructure.validation.settings import PlanValidationSettings


class PlanValidator(PlanValidatorPort):
    """Runs the configured validation checks before any step is executed."""

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
        self._error_factory = error_factory or PlanValidationErrorFactory(module=__name__)
        settings = PlanValidationSettings(
            workspace_root=(
                Path(workspace_root) if workspace_root is not None else Path.cwd()
            ).resolve(strict=False),
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
            else build_default_checks(registry, settings, self._error_factory)
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

        for check in self._checks:
            check.validate(plan)


__all__ = ["PlanValidationError", "PlanValidator"]
