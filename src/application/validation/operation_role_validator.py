"""Operation-slot role validation for execution plans."""

from __future__ import annotations

from typing import Literal

from application.validation.errors import PlanValidationErrorFactory
from application.validation.operations import OperationCatalog
from domain.entities.plan import ExecutionPlan
from domain.entities.registry import ModuleMetadata

OperationSlot = Literal["source", "transformation", "destination"]


def _requires_pipeline_input(metadata: ModuleMetadata) -> bool:
    return any(item.pipeline_input and item.required for item in metadata.inputs)


class OperationRoleValidator:
    """Ensures sources read, transformations transform, and destinations write."""

    def __init__(
        self,
        catalog: OperationCatalog,
        error_factory: PlanValidationErrorFactory | None = None,
    ) -> None:
        self._catalog = catalog
        self._error_factory = error_factory or PlanValidationErrorFactory()

    def validate(self, plan: ExecutionPlan) -> None:
        if plan.source is not None:
            self._validate(
                operation=plan.source.operation,
                slot="source",
                label="source",
            )
        for step in plan.transformations:
            self._validate(
                operation=step.operation,
                slot="transformation",
                label=f"transformation[{step.step_id}]",
            )
        if plan.destination is not None:
            self._validate(
                operation=plan.destination.operation,
                slot="destination",
                label="destination",
            )

    def _validate(self, *, operation: str, slot: OperationSlot, label: str) -> None:
        metadata = self._catalog.metadata(operation)
        if slot == "source":
            expected = "read-only source"
            if metadata.side_effects:
                self._raise(
                    label=label, operation=operation, expected=expected, reason="write_operation"
                )
            if _requires_pipeline_input(metadata):
                self._raise(
                    label=label,
                    operation=operation,
                    expected=expected,
                    reason="requires_pipeline_input",
                )
        elif slot == "transformation":
            expected = "transformation"
            if not _requires_pipeline_input(metadata):
                self._raise(
                    label=label,
                    operation=operation,
                    expected=expected,
                    reason="missing_pipeline_input",
                )
            if metadata.side_effects:
                self._raise(
                    label=label, operation=operation, expected=expected, reason="write_operation"
                )
        else:
            expected = "write destination"
            if not metadata.side_effects:
                self._raise(
                    label=label,
                    operation=operation,
                    expected=expected,
                    reason="not_a_write_operation",
                )

    def _raise(
        self,
        *,
        label: str,
        operation: str,
        expected: str,
        reason: str,
    ) -> None:
        raise self._error_factory.error(
            code="PLAN_INVALID_OPERATION_ROLE",
            message="Operation is not valid in this plan slot",
            context={
                "step": label,
                "operation": operation,
                "expected": expected,
                "reason": reason,
            },
        )


__all__ = ["OperationRoleValidator", "OperationSlot"]
