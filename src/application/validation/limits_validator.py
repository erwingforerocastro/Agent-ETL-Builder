"""Size and step-count validation for execution plans."""

from __future__ import annotations

from application.ports.plan_sizer import PlanSizerPort
from application.validation.errors import PlanValidationErrorFactory
from application.validation.settings import PlanValidationSettings
from domain.entities.plan import ExecutionPlan


class LimitsValidator:
    """Enforces step, chunk-size, and serialized-size limits."""

    def __init__(
        self,
        settings: PlanValidationSettings,
        sizer: PlanSizerPort,
        error_factory: PlanValidationErrorFactory | None = None,
    ) -> None:
        self._settings = settings
        self._sizer = sizer
        self._error_factory = error_factory or PlanValidationErrorFactory()

    def validate(self, plan: ExecutionPlan) -> None:
        if len(plan.transformations) > self._settings.max_steps:
            raise self._error_factory.error(
                code="PLAN_TOO_MANY_STEPS",
                message="Plan exceeds maximum step count",
                context={
                    "steps": len(plan.transformations),
                    "max_steps": self._settings.max_steps,
                },
            )
        if (
            not isinstance(plan.chunking.size, int)
            or isinstance(plan.chunking.size, bool)
            or plan.chunking.size <= 0
            or plan.chunking.size > self._settings.max_chunk_size
        ):
            raise self._error_factory.error(
                code="PLAN_INVALID_CHUNK_SIZE",
                message="Chunk size out of range",
                context={
                    "size": plan.chunking.size,
                    "max": self._settings.max_chunk_size,
                },
            )

        size = self._sizer.size_bytes(plan)
        if size > self._settings.max_plan_bytes:
            raise self._error_factory.error(
                code="PLAN_TOO_LARGE",
                message="Plan exceeds the maximum serialized size",
                context={"bytes": size, "max_bytes": self._settings.max_plan_bytes},
            )
