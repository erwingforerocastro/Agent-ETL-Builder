"""Approval requirement validation for execution plans."""

from __future__ import annotations

from domain.entities.plan import ExecutionPlan
from infrastructure.validation.errors import PlanValidationErrorFactory
from infrastructure.validation.operations import OperationPolicy, iter_operations


class ApprovalValidator:
    """Requires approval for writes, destructive actions, and assessment safety."""

    def __init__(
        self,
        policy: OperationPolicy,
        error_factory: PlanValidationErrorFactory | None = None,
    ) -> None:
        self._policy = policy
        self._error_factory = error_factory or PlanValidationErrorFactory()

    def validate(self, plan: ExecutionPlan) -> None:
        requiring_approval = [
            call.operation for call in iter_operations(plan) if self._policy.requires_approval(call)
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
