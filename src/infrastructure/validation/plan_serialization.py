"""Canonical JSON serialization shared by plan size and hash adapters."""

from __future__ import annotations

import json
from typing import NoReturn

from application.validation.errors import PlanValidationErrorFactory
from domain.entities.plan import ExecutionPlan, PlanDestination, PlanSource


def serialize_plan(
    plan: ExecutionPlan,
    *,
    error_factory: PlanValidationErrorFactory | None = None,
) -> bytes:
    """Serialize a plan deterministically for size measurement and hashing."""
    factory = error_factory or PlanValidationErrorFactory(module=__name__)
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
            sort_keys=True,
            default=_json_default,
        )
    except (TypeError, ValueError) as exc:
        raise factory.error(
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


__all__ = ["serialize_plan"]
