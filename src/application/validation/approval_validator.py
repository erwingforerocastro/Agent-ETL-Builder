"""Approval requirement validation for execution plans."""

from __future__ import annotations

from application.validation.errors import PlanValidationErrorFactory
from application.validation.operations import (
    OperationCatalog,
    OperationSafetyPolicy,
    iter_operations,
)
from domain.entities.plan import ExecutionPlan


class ApprovalValidator:
    """Requires approval for writes, destructive actions, and assessment safety."""

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
        requiring_approval = [
            call.operation
            for call in iter_operations(plan)
            if self._safety.requires_approval(
                call,
                self._catalog.metadata(call.operation),
            )
        ]
        if not requiring_approval:
            return
        if plan.mode == "assessment":
            raise self._error_factory.error(
                code="PLAN_UNSAFE_OPERATION",
                message="Assessment plans must not perform writes or destructive actions",
                context={"operations": requiring_approval},
            )
        if not plan.approval_required:
            raise self._error_factory.error(
                code="PLAN_APPROVAL_REQUIRED",
                message="This plan requires human approval",
                context={"operations": requiring_approval},
            )
