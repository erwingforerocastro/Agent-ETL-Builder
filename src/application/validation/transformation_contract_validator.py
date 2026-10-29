"""Idempotence and cross-parameter semantics for transformation steps."""

from __future__ import annotations

from application.validation.errors import PlanValidationErrorFactory
from application.validation.operations import OperationCatalog
from domain.entities.plan import ExecutionPlan, PlanTransformation

_NULL_FILTER_OPERATORS = frozenset({"is_null", "is_not_null"})
_TEXT_FILTER_OPERATORS = frozenset({"contains", "starts_with", "ends_with"})
_SUMMARY_FILL_METHODS = frozenset({"mean", "median", "mode"})


class TransformationContractValidator:
    """Enforces transformation idempotence and cross-parameter rules."""

    def __init__(
        self,
        catalog: OperationCatalog,
        error_factory: PlanValidationErrorFactory | None = None,
    ) -> None:
        self._catalog = catalog
        self._error_factory = error_factory or PlanValidationErrorFactory()

    def validate(self, plan: ExecutionPlan) -> None:
        for step in plan.transformations:
            metadata = self._catalog.metadata(step.operation)
            if not metadata.idempotent:
                raise self._error_factory.error(
                    code="PLAN_NON_IDEMPOTENT_TRANSFORMATION",
                    message="Transformation operations must be idempotent",
                    context={
                        "step": f"transformation[{step.step_id}]",
                        "operation": step.operation,
                    },
                )
            self._validate_semantics(step)

    def _validate_semantics(self, step: PlanTransformation) -> None:
        if step.operation == "filter_rows":
            self._validate_filter(step)
        elif step.operation == "fill_missing_values":
            self._validate_fill(step)
        elif step.operation == "normalize_dates":
            self._validate_dates(step)

    def _validate_filter(self, step: PlanTransformation) -> None:
        operator = step.params.get("operator")
        value = step.params.get("value")
        if operator in _NULL_FILTER_OPERATORS:
            if value is not None:
                self._invalid(step, "value", "Null filters must not supply a value")
            return
        if value is None:
            self._invalid(step, "value", "Filter operators require a value")
        if operator in _TEXT_FILTER_OPERATORS and not isinstance(value, str):
            self._invalid(step, "value", "Text filters require a string value")

    def _validate_fill(self, step: PlanTransformation) -> None:
        method = step.params.get("method", "constant")
        value = step.params.get("value")
        if method == "constant":
            if value is None:
                self._invalid(step, "value", "Constant imputation requires a value")
        elif value is not None:
            self._invalid(step, "value", "Summary imputation must not supply a value")

    def _validate_dates(self, step: PlanTransformation) -> None:
        output_format = step.params.get("output_format")
        if not isinstance(output_format, str) or not output_format.strip():
            self._invalid(
                step,
                "output_format",
                "Date output format must contain non-whitespace text",
            )

    def _invalid(self, step: PlanTransformation, argument: str, message: str) -> None:
        raise self._error_factory.error(
            code="PLAN_INVALID_ARGUMENT",
            message=message,
            context={
                "step": f"transformation[{step.step_id}]",
                "operation": step.operation,
                "argument": argument,
            },
        )


__all__ = ["TransformationContractValidator"]
