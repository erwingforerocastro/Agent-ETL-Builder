"""Operation traversal, registry lookup, and side-effect policy."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass

from application.ports.module_registry import ModuleRegistryReadPort
from application.validation.constants import (
    DESTRUCTIVE_OPERATIONS,
    WRITE_OPERATION_TOKENS,
    WRITE_SIDE_EFFECT_TOKENS,
)
from application.validation.errors import PlanValidationErrorFactory
from domain.entities.plan import ExecutionPlan
from domain.entities.registry import ModuleMetadata


@dataclass(frozen=True, slots=True)
class OperationCall:
    """One source, transformation, or destination call in a plan."""

    label: str
    operation: str
    params: Mapping[str, object]


def iter_operations(plan: ExecutionPlan) -> Iterator[OperationCall]:
    """Yield every operation call in execution order."""
    if plan.source is not None:
        yield OperationCall(
            label="source",
            operation=plan.source.operation,
            params=plan.source.params,
        )
    for step in plan.transformations:
        yield OperationCall(
            label=f"transformation[{step.step_id}]",
            operation=step.operation,
            params=step.params,
        )
    if plan.destination is not None:
        yield OperationCall(
            label="destination",
            operation=plan.destination.operation,
            params=plan.destination.params,
        )


class OperationCatalog:
    """Resolves operation names to allowlisted registry metadata."""

    def __init__(
        self,
        registry: ModuleRegistryReadPort,
        error_factory: PlanValidationErrorFactory | None = None,
    ) -> None:
        self._registry = registry
        self._error_factory = error_factory or PlanValidationErrorFactory()

    def metadata(self, operation: str) -> ModuleMetadata:
        metadata = self._registry.get(operation)
        if metadata is None:
            raise self._error_factory.error(
                code="PLAN_UNKNOWN_OPERATION",
                message="Operation is not allowlisted in the registry",
                context={"operation": operation},
            )
        return metadata


class OperationSafetyPolicy:
    """Classifies write, destructive, and approval-requiring operations."""

    def requires_approval(self, call: OperationCall, metadata: ModuleMetadata) -> bool:
        return self.is_write(call.operation, metadata) or self.is_destructive(
            call.operation, call.params
        )

    def is_read_only(self, call: OperationCall, metadata: ModuleMetadata) -> bool:
        return not self.is_write(call.operation, metadata) and not self.is_destructive(
            call.operation, call.params
        )

    @staticmethod
    def is_write(operation: str, metadata: ModuleMetadata) -> bool:
        side_effects = " ".join(metadata.side_effects).lower()
        if any(token in side_effects for token in WRITE_SIDE_EFFECT_TOKENS):
            return True
        operation_lower = operation.lower()
        return any(token in operation_lower for token in WRITE_OPERATION_TOKENS)

    @staticmethod
    def is_destructive(operation: str, params: Mapping[str, object]) -> bool:
        if operation in DESTRUCTIVE_OPERATIONS:
            return True
        if operation in {"cast_column", "normalize_dates"}:
            return params.get("errors") == "coerce"
        return operation == "replace_values" and params.get("new") is None


__all__ = [
    "OperationCall",
    "OperationCatalog",
    "OperationSafetyPolicy",
    "iter_operations",
]
