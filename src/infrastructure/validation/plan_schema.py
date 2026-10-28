"""Strict Pydantic schema for structured execution plans."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from domain.entities.plan import (
    ExecutionPlan,
    PlanChunking,
    PlanDestination,
    PlanSource,
    PlanTransformation,
)
from infrastructure.validation.constants import (
    OPERATION_PATTERN,
    RUN_ID_PATTERN,
    SCHEMA_MAX_PARAM_DEPTH,
    SCHEMA_MAX_PARAM_ITEMS,
    SCHEMA_MAX_STRING_LENGTH,
    STEP_ID_PATTERN,
)
from infrastructure.validation.errors import PlanValidationError


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


def _validate_json_value(value: object, *, path: str, depth: int = 0) -> None:
    """Reject values that cannot be represented safely in a JSON plan."""
    if depth > SCHEMA_MAX_PARAM_DEPTH:
        raise ValueError(f"{path} exceeds the maximum nesting depth")
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must be a finite number")
        return
    if isinstance(value, str):
        if len(value) > SCHEMA_MAX_STRING_LENGTH:
            raise ValueError(f"{path} exceeds the maximum string length")
        if "\x00" in value:
            raise ValueError(f"{path} must not contain null bytes")
        return
    if isinstance(value, list | tuple):
        if len(value) > SCHEMA_MAX_PARAM_ITEMS:
            raise ValueError(f"{path} contains too many items")
        for index, item in enumerate(value):
            _validate_json_value(item, path=f"{path}[{index}]", depth=depth + 1)
        return
    if isinstance(value, Mapping):
        if len(value) > SCHEMA_MAX_PARAM_ITEMS:
            raise ValueError(f"{path} contains too many entries")
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} contains a non-string key")
            if len(key) > 128:
                raise ValueError(f"{path} contains an overlong key")
            _validate_json_value(item, path=f"{path}.{key}", depth=depth + 1)
        return
    raise ValueError(f"{path} has an unsupported type: {type(value).__name__}")


class _OperationSchema(_StrictModel):
    operation: str = Field(min_length=1, max_length=128, pattern=OPERATION_PATTERN.pattern)
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("params")
    @classmethod
    def _check_params(cls, value: dict[str, Any]) -> dict[str, Any]:
        _validate_json_value(value, path="params")
        return value


class PlanSourceSchema(_OperationSchema):
    """Source step in a structured plan."""


class PlanDestinationSchema(_OperationSchema):
    """Destination step in a structured plan."""


class PlanTransformationSchema(_OperationSchema):
    """Transformation step in a structured plan."""

    step_id: str = Field(min_length=1, max_length=128, pattern=STEP_ID_PATTERN.pattern)


class PlanChunkingSchema(_StrictModel):
    """Chunking configuration."""

    enabled: bool
    size: int = Field(gt=0)


class ExecutionPlanSchema(_StrictModel):
    """Validated JSON representation of an execution plan."""

    plan_version: Literal["1.0"]
    mode: Literal["pipeline", "assessment"]
    run_id: str = Field(min_length=1, max_length=128, pattern=RUN_ID_PATTERN.pattern)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2_000)
    source: PlanSourceSchema | None = None
    transformations: list[PlanTransformationSchema] = Field(default_factory=list)
    destination: PlanDestinationSchema | None = None
    chunking: PlanChunkingSchema
    on_error: Literal["fail_fast", "continue"]
    approval_required: bool

    @model_validator(mode="after")
    def _check_mode_contract(self) -> ExecutionPlanSchema:
        if self.mode == "assessment":
            if self.destination is not None:
                raise ValueError("assessment plans must not have a destination")
        else:
            if self.source is None:
                raise ValueError("pipeline plans must have a source")
            if self.destination is None:
                raise ValueError("pipeline plans must have a destination")

        step_ids = [step.step_id for step in self.transformations]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("step_id values must be unique")
        return self

    def to_domain(self) -> ExecutionPlan:
        """Convert the validated schema into domain entities."""
        return ExecutionPlan(
            plan_version=self.plan_version,
            mode=self.mode,
            run_id=self.run_id,
            name=self.name,
            description=self.description,
            source=(
                PlanSource(operation=self.source.operation, params=self.source.params)
                if self.source is not None
                else None
            ),
            transformations=tuple(
                PlanTransformation(
                    step_id=step.step_id,
                    operation=step.operation,
                    params=step.params,
                )
                for step in self.transformations
            ),
            destination=(
                PlanDestination(
                    operation=self.destination.operation,
                    params=self.destination.params,
                )
                if self.destination is not None
                else None
            ),
            chunking=PlanChunking(enabled=self.chunking.enabled, size=self.chunking.size),
            on_error=self.on_error,
            approval_required=self.approval_required,
        )


# Short alias for callers that only need the plan schema.
PlanSchema = ExecutionPlanSchema


def parse_plan(payload: Mapping[str, object]) -> ExecutionPlan:
    """Validate a JSON-compatible plan payload and convert it to domain entities."""
    try:
        schema = ExecutionPlanSchema.model_validate(payload)
    except ValidationError as exc:
        details = [
            {
                "location": ".".join(
                    str(part) for part in cast(tuple[object, ...], error.get("loc", ()))
                ),
                "type": error.get("type", "value_error"),
                "message": error.get("msg", "Invalid value"),
            }
            for error in exc.errors(include_url=False, include_input=False)
        ]
        raise PlanValidationError(
            code="PLAN_INVALID_SCHEMA",
            message="Plan payload does not match the schema",
            module=__name__,
            context={"errors": details},
        ) from exc
    return schema.to_domain()


__all__ = [
    "ExecutionPlanSchema",
    "PlanChunkingSchema",
    "PlanDestinationSchema",
    "PlanSchema",
    "PlanSourceSchema",
    "PlanTransformationSchema",
    "parse_plan",
]
