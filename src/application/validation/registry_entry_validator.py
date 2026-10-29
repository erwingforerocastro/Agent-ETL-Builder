"""Registry and assessment-safety validation for plan operations."""

from __future__ import annotations

from application.validation.errors import PlanValidationErrorFactory
from application.validation.operations import (
    OperationCatalog,
    OperationSafetyPolicy,
    iter_operations,
)
from domain.entities.plan import ExecutionPlan


class RegistryEntryValidator:
    """Ensures every operation is allowlisted and assessment plans stay read-only."""

    def __init__(
        self,
        catalog: OperationCatalog,
        safety: OperationSafetyPolicy,
        error_factory: PlanValidationErrorFactory | None = None,
    ) -> None:
        self._catalog = catalog
        self._safety = safety
        self._error_factory = error_factory or PlanValidationErrorFactory()

    def validate(self, plan: ExecutionPlan) -> None:
        for call in iter_operations(plan):
            metadata = self._catalog.metadata(call.operation)
            if plan.mode == "assessment" and not self._safety.is_read_only(call, metadata):
                raise self._error_factory.error(
                    code="PLAN_UNSAFE_OPERATION",
                    message="Assessment plans may only call read-only operations",
                    context={
                        "step": call.label,
                        "operation": call.operation,
                        "side_effects": metadata.side_effects,
                    },
                )
