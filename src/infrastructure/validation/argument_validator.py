"""Argument validation for plan operations."""

from __future__ import annotations

from domain.entities.plan import ExecutionPlan
from domain.entities.registry import ModuleInput
from infrastructure.registry.validators import TypeValidator
from infrastructure.validation.errors import PlanValidationErrorFactory
from infrastructure.validation.operations import OperationPolicy, iter_operations
from infrastructure.validation.path_validator import PathValueValidator


class ArgumentValidator:
    """Validates argument names, presence, types, and declared constraints."""

    def __init__(
        self,
        policy: OperationPolicy,
        path_validator: PathValueValidator,
        error_factory: PlanValidationErrorFactory | None = None,
        type_validator: TypeValidator | None = None,
    ) -> None:
        self._policy = policy
        self._path_validator = path_validator
        self._error_factory = error_factory or PlanValidationErrorFactory()
        self._type_validator = type_validator or TypeValidator()

    def validate(self, plan: ExecutionPlan) -> None:
        for call in iter_operations(plan):
            metadata = self._policy.metadata(call.operation)
            caller_inputs = {item.name: item for item in metadata.inputs if not item.pipeline_input}
            pipeline_inputs = {item.name for item in metadata.inputs if item.pipeline_input}
            supplied = set(call.params)

            managed = sorted(supplied & pipeline_inputs)
            if managed:
                raise self._error_factory.error(
                    code="PLAN_PIPELINE_ARGUMENT",
                    message="Plan must not supply pipeline-managed arguments",
                    context={
                        "step": call.label,
                        "operation": call.operation,
                        "arguments": managed,
                    },
                )

            unknown = sorted(supplied - set(caller_inputs))
            if unknown:
                raise self._error_factory.error(
                    code="PLAN_UNKNOWN_ARGUMENT",
                    message="Plan supplies arguments that the module does not accept",
                    context={
                        "step": call.label,
                        "operation": call.operation,
                        "arguments": unknown,
                    },
                )

            missing = sorted(
                name
                for name, definition in caller_inputs.items()
                if definition.required and name not in supplied
            )
            if missing:
                raise self._error_factory.error(
                    code="PLAN_MISSING_ARGUMENT",
                    message="Plan is missing required arguments",
                    context={
                        "step": call.label,
                        "operation": call.operation,
                        "arguments": missing,
                    },
                )

            for name, value in call.params.items():
                definition = caller_inputs[name]
                if not self._type_validator.value_matches_type(value, definition.type):
                    raise self._error_factory.error(
                        code="PLAN_INVALID_ARGUMENT_TYPE",
                        message="Argument value does not match the declared type",
                        context={
                            "step": call.label,
                            "operation": call.operation,
                            "argument": name,
                            "expected": definition.type,
                        },
                    )
                self._validate_constraints(
                    label=call.label,
                    operation=call.operation,
                    definition=definition,
                    value=value,
                )

    def _validate_constraints(
        self,
        *,
        label: str,
        operation: str,
        definition: ModuleInput,
        value: object,
    ) -> None:
        for constraint in definition.constraints:
            text = constraint.lower()
            if (
                "non-empty when provided" in text
                and value is not None
                and isinstance(value, str | list | tuple | dict)
                and len(value) == 0
            ):
                raise self._error_factory.error(
                    code="PLAN_INVALID_ARGUMENT",
                    message="Argument must not be empty when provided",
                    context={
                        "step": label,
                        "operation": operation,
                        "argument": definition.name,
                    },
                )
            if "column name" in text and isinstance(value, str) and not value.strip():
                raise self._error_factory.error(
                    code="PLAN_INVALID_ARGUMENT",
                    message="Column names must not be blank",
                    context={
                        "step": label,
                        "operation": operation,
                        "argument": definition.name,
                    },
                )
            if (
                "column names must exist" in text
                and isinstance(value, list | tuple)
                and any(not isinstance(item, str) or not item.strip() for item in value)
            ):
                raise self._error_factory.error(
                    code="PLAN_INVALID_ARGUMENT",
                    message="Column names must be non-blank strings",
                    context={
                        "step": label,
                        "operation": operation,
                        "argument": definition.name,
                    },
                )
            if "path" in text:
                self._path_validator.validate(value, label=f"{label}.{definition.name}")
