"""Strict parser for model-generated transformation drafts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from application.validation.constants import OPERATION_PATTERN
from domain.entities.plan import PlanTransformation
from domain.entities.plan_draft import PlanDraft
from domain.errors import PlanSynthesisError

_MAX_DRAFT_TRANSFORMATIONS = 20


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class _TransformationSchema(_StrictModel):
    operation: str = Field(min_length=1, max_length=128, pattern=OPERATION_PATTERN.pattern)
    params: dict[str, Any] = Field(default_factory=dict)


class _DraftSchema(_StrictModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2_000)
    transformations: list[_TransformationSchema] = Field(
        default_factory=list,
        max_length=_MAX_DRAFT_TRANSFORMATIONS,
    )
    questions: list[str] = Field(default_factory=list, max_length=10)
    missing_inputs: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("name", "description")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped

    @field_validator("questions", "missing_inputs")
    @classmethod
    def _strip_items(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            stripped = value.strip()
            if not stripped:
                raise ValueError("items must not be blank")
            if len(stripped) > 500:
                raise ValueError("items must not exceed 500 characters")
            cleaned.append(stripped)
        return cleaned


def _invalid(context: Mapping[str, object]) -> PlanSynthesisError:
    return PlanSynthesisError(
        code="PLAN_SYNTHESIS_INVALID",
        message="Plan draft does not match the schema",
        module=__name__,
        context=context,
    )


def _normalized_params(params: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(params)
    for name, value in tuple(normalized.items()):
        if value is None or (isinstance(value, list) and not value):
            del normalized[name]
    return normalized


def parse_plan_draft(payload: Mapping[str, object]) -> PlanDraft:
    """Validate a model draft, normalize optional values, and assign step IDs."""
    try:
        schema = _DraftSchema.model_validate(payload)
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
        raise _invalid({"errors": details}) from exc
    try:
        transformations = tuple(
            PlanTransformation(
                step_id=f"s{index}",
                operation=item.operation,
                params=_normalized_params(item.params),
            )
            for index, item in enumerate(schema.transformations, start=1)
        )
        return PlanDraft(
            name=schema.name,
            description=schema.description,
            transformations=transformations,
            questions=tuple(schema.questions),
            missing_inputs=tuple(schema.missing_inputs),
        )
    except ValueError as exc:
        raise _invalid({"reason": str(exc)}) from exc


__all__ = ["parse_plan_draft"]
