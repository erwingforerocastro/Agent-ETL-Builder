"""Size and step-count validation for execution plans."""

from __future__ import annotations

import json
from typing import NoReturn

from application.validation.errors import PlanValidationErrorFactory
from application.validation.settings import PlanValidationSettings
from domain.entities.plan import ExecutionPlan, PlanDestination, PlanSource


class LimitsValidator:
    """Enforces step, chunk-size, and serialized-size limits."""

    def __init__(
        self,
        settings: PlanValidationSettings,
        error_factory: PlanValidationErrorFactory | None = None,
    ) -> None:
        self._settings = settings
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

        size = len(serialize_plan(plan, self._error_factory))
        if size > self._settings.max_plan_bytes:
            raise self._error_factory.error(
                code="PLAN_TOO_LARGE",
                message="Plan exceeds the maximum serialized size",
                context={"bytes": size, "max_bytes": self._settings.max_plan_bytes},
            )


def serialize_plan(
    plan: ExecutionPlan,
    error_factory: PlanValidationErrorFactory,
) -> bytes:
    """Serialize a plan to compact UTF-8 JSON for size validation."""
    payload: dict[str, object] = {
        "plan_version": plan.plan_version,
        "mode": plan.mode,
        "run_id": plan.run_id,
        "name": plan.name,
        "description": plan.description,
        "source": _operation_payload(plan.source),
        "transformations": [
            {
                "step_id": step.step_id,
                "operation": step.operation,
                "params": dict(step.params),
            }
            for step in plan.transformations
        ],
        "destination": _operation_payload(plan.destination),
        "chunking": {"enabled": plan.chunking.enabled, "size": plan.chunking.size},
        "on_error": plan.on_error,
        "approval_required": plan.approval_required,
    }
    try:
        text = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            default=_json_default,
        )
    except (TypeError, ValueError) as exc:
        raise error_factory.error(
            code="PLAN_UNSERIALIZABLE",
            message="Plan contains values that cannot be serialized safely",
        ) from exc
    return text.encode("utf-8")


def _operation_payload(
    operation: PlanSource | PlanDestination | None,
) -> dict[str, object] | None:
    if operation is None:
        return None
    return {"operation": operation.operation, "params": dict(operation.params)}


def _json_default(value: object) -> NoReturn:
    raise TypeError(f"Unsupported plan value: {type(value).__name__}")
