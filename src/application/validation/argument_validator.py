"""Argument validation for plan operations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from application.validation.errors import PlanValidationError, PlanValidationErrorFactory
from application.validation.operations import OperationCall, OperationCatalog, iter_operations
from application.validation.path_validator import PathValueValidator
from application.validation.types import value_matches_type
from domain.entities.plan import ExecutionPlan
from domain.entities.registry import Constraint, ConstraintKind, ModuleInput


@dataclass(frozen=True, slots=True)
class _ConstraintContext:
    call: OperationCall
    definition: ModuleInput
    value: object


_ConstraintCheck = Callable[[Constraint, _ConstraintContext], None]


class ArgumentValidator:
    """Validates argument names, presence, types, and declared constraints."""

    def __init__(
        self,
        catalog: OperationCatalog,
        path_validator: PathValueValidator,
        error_factory: PlanValidationErrorFactory | None = None,
    ) -> None:
        self._catalog = catalog
        self._path_validator = path_validator
        self._error_factory = error_factory or PlanValidationErrorFactory()
        self._constraint_checks: dict[ConstraintKind, _ConstraintCheck] = {
            ConstraintKind.NON_EMPTY: self._check_non_empty,
            ConstraintKind.COLUMN_NAME: self._check_column_name,
            ConstraintKind.COLUMN_NAMES: self._check_column_names,
            ConstraintKind.COLUMN_EXISTS: self._check_column_names,
            ConstraintKind.TEXT_COLUMNS: self._check_column_names,
            ConstraintKind.ENUM: self._check_enum,
            ConstraintKind.PATH: self._check_path,
        }

    def validate(self, plan: ExecutionPlan) -> None:
        for call in iter_operations(plan):
            metadata = self._catalog.metadata(call.operation)
            caller_inputs = {item.name: item for item in metadata.inputs if not item.pipeline_input}
            pipeline_inputs = {item.name for item in metadata.inputs if item.pipeline_input}
            supplied = set(call.params)

            self._reject_pipeline_arguments(call, supplied, pipeline_inputs)
            self._reject_unknown_arguments(call, supplied, caller_inputs)
            self._reject_missing_arguments(call, supplied, caller_inputs)

            for name, value in call.params.items():
                self._validate_value(call, caller_inputs[name], value)

    def _reject_pipeline_arguments(
        self,
        call: OperationCall,
        supplied: set[str],
        pipeline_inputs: set[str],
    ) -> None:
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

    def _reject_unknown_arguments(
        self,
        call: OperationCall,
        supplied: set[str],
        caller_inputs: dict[str, ModuleInput],
    ) -> None:
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

    def _reject_missing_arguments(
        self,
        call: OperationCall,
        supplied: set[str],
        caller_inputs: dict[str, ModuleInput],
    ) -> None:
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

    def _validate_value(
        self,
        call: OperationCall,
        definition: ModuleInput,
        value: object,
    ) -> None:
        if not value_matches_type(value, definition.type):
            raise self._error_factory.error(
                code="PLAN_INVALID_ARGUMENT_TYPE",
                message="Argument value does not match the declared type",
                context={
                    "step": call.label,
                    "operation": call.operation,
                    "argument": definition.name,
                    "expected": definition.type,
                },
            )
        context = _ConstraintContext(call=call, definition=definition, value=value)
        for constraint in definition.constraints:
            self._constraint_checks[constraint.kind](constraint, context)

    def _check_non_empty(self, _constraint: Constraint, context: _ConstraintContext) -> None:
        value = context.value
        if value is not None and isinstance(value, str | list | tuple | dict) and len(value) == 0:
            raise self._invalid(context, "Argument must not be empty when provided")

    def _check_column_name(self, _constraint: Constraint, context: _ConstraintContext) -> None:
        if isinstance(context.value, str) and not context.value.strip():
            raise self._invalid(context, "Column names must not be blank")

    def _check_column_names(self, _constraint: Constraint, context: _ConstraintContext) -> None:
        value = context.value
        if isinstance(value, str):
            items: tuple[object, ...] = (value,)
        elif isinstance(value, list | tuple):
            items = tuple(value)
        else:
            items = ()
        if any(not isinstance(item, str) or not item.strip() for item in items):
            raise self._invalid(context, "Column names must be non-blank strings")

    def _check_enum(self, constraint: Constraint, context: _ConstraintContext) -> None:
        if not isinstance(context.value, str) or context.value not in constraint.values:
            raise self._error_factory.error(
                code="PLAN_INVALID_ARGUMENT",
                message="Argument is not one of the allowed values",
                context={
                    "step": context.call.label,
                    "operation": context.call.operation,
                    "argument": context.definition.name,
                    "allowed": constraint.values,
                },
            )

    def _check_path(self, _constraint: Constraint, context: _ConstraintContext) -> None:
        self._path_validator.validate(
            context.value,
            label=f"{context.call.label}.{context.definition.name}",
        )

    def _invalid(self, context: _ConstraintContext, message: str) -> PlanValidationError:
        return self._error_factory.error(
            code="PLAN_INVALID_ARGUMENT",
            message=message,
            context={
                "step": context.call.label,
                "operation": context.call.operation,
                "argument": context.definition.name,
            },
        )
