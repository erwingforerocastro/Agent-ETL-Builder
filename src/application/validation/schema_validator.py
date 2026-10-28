"""Schema-level validation of execution plans."""

from __future__ import annotations

from collections.abc import Mapping

from application.validation.constants import (
    ON_ERROR_POLICIES,
    OPERATION_PATTERN,
    PLAN_MODES,
    STEP_ID_PATTERN,
    SUPPORTED_PLAN_VERSIONS,
)
from application.validation.errors import PlanValidationErrorFactory
from application.validation.operations import iter_operations
from domain.entities.plan import (
    ExecutionPlan,
    PlanChunking,
    PlanDestination,
    PlanSource,
    PlanTransformation,
)


class SchemaValidator:
    """Validates the shape of a plan and the syntax of its operations."""

    def __init__(self, error_factory: PlanValidationErrorFactory | None = None) -> None:
        self._error_factory = error_factory or PlanValidationErrorFactory()

    def validate(self, plan: ExecutionPlan) -> None:
        self._validate_header(plan)
        self._validate_operations(plan)

    def _validate_header(self, plan: ExecutionPlan) -> None:
        if plan.plan_version not in SUPPORTED_PLAN_VERSIONS:
            raise self._error_factory.error(
                code="PLAN_INVALID_SCHEMA",
                message="plan_version must be 1.0",
                context={"plan_version": plan.plan_version},
            )
        if plan.mode not in PLAN_MODES:
            raise self._error_factory.error(
                code="PLAN_INVALID_SCHEMA",
                message="mode must be pipeline or assessment",
                context={"mode": plan.mode},
            )
        if plan.on_error not in ON_ERROR_POLICIES:
            raise self._error_factory.error(
                code="PLAN_INVALID_SCHEMA",
                message="on_error must be fail_fast or continue",
                context={"on_error": plan.on_error},
            )
        if not isinstance(plan.approval_required, bool):
            raise self._error_factory.error(
                code="PLAN_INVALID_SCHEMA",
                message="approval_required must be a boolean",
            )
        if not isinstance(plan.chunking, PlanChunking):
            raise self._error_factory.error(
                code="PLAN_INVALID_SCHEMA",
                message="chunking must be a PlanChunking value",
            )
        if not isinstance(plan.chunking.enabled, bool):
            raise self._error_factory.error(
                code="PLAN_INVALID_SCHEMA",
                message="chunking.enabled must be a boolean",
            )
        if plan.mode == "assessment" and plan.destination is not None:
            raise self._error_factory.error(
                code="PLAN_INVALID_SCHEMA",
                message="Assessment plans must not have a destination",
            )
        if plan.mode == "pipeline" and plan.source is None:
            raise self._error_factory.error(
                code="PLAN_INVALID_SCHEMA",
                message="Pipeline plans must have a source",
            )
        if plan.mode == "pipeline" and plan.destination is None:
            raise self._error_factory.error(
                code="PLAN_INVALID_SCHEMA",
                message="Pipeline plans must have a destination",
            )
        if plan.source is not None and not isinstance(plan.source, PlanSource):
            raise self._error_factory.error(
                code="PLAN_INVALID_SCHEMA",
                message="source must be a PlanSource value",
            )
        if plan.destination is not None and not isinstance(plan.destination, PlanDestination):
            raise self._error_factory.error(
                code="PLAN_INVALID_SCHEMA",
                message="destination must be a PlanDestination value",
            )

        step_ids: list[str] = []
        for step in plan.transformations:
            if not isinstance(step, PlanTransformation):
                raise self._error_factory.error(
                    code="PLAN_INVALID_SCHEMA",
                    message="transformations must contain only PlanTransformation values",
                )
            if not STEP_ID_PATTERN.fullmatch(step.step_id):
                raise self._error_factory.error(
                    code="PLAN_INVALID_SCHEMA",
                    message="step_id contains unsupported characters",
                    context={"step_id": step.step_id},
                )
            step_ids.append(step.step_id)
        if len(step_ids) != len(set(step_ids)):
            raise self._error_factory.error(
                code="PLAN_DUPLICATE_STEP_ID",
                message="step_id values must be unique",
            )

    def _validate_operations(self, plan: ExecutionPlan) -> None:
        for call in iter_operations(plan):
            if not OPERATION_PATTERN.fullmatch(call.operation):
                raise self._error_factory.error(
                    code="PLAN_INVALID_SCHEMA",
                    message="operation contains unsupported characters",
                    context={"step": call.label, "operation": call.operation},
                )
            if not isinstance(call.params, Mapping):
                raise self._error_factory.error(
                    code="PLAN_INVALID_SCHEMA",
                    message="params must be a mapping",
                    context={"step": call.label},
                )
            for key in call.params:
                if not isinstance(key, str):
                    raise self._error_factory.error(
                        code="PLAN_INVALID_SCHEMA",
                        message="param names must be strings",
                        context={"step": call.label},
                    )
