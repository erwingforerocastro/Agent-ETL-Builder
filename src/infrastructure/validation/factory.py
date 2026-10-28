"""Default dependency wiring for plan validation checks."""

from __future__ import annotations

from application.ports.module_registry import ModuleRegistryPort
from infrastructure.validation.approval_validator import ApprovalValidator
from infrastructure.validation.argument_validator import ArgumentValidator
from infrastructure.validation.errors import PlanValidationErrorFactory
from infrastructure.validation.limits_validator import LimitsValidator
from infrastructure.validation.operations import OperationPolicy
from infrastructure.validation.path_validator import PathValueValidator, PlanPathValidator
from infrastructure.validation.plan_check import PlanCheck
from infrastructure.validation.registry_entry_validator import RegistryEntryValidator
from infrastructure.validation.schema_validator import SchemaValidator
from infrastructure.validation.security_validator import SecurityValidator
from infrastructure.validation.settings import PlanValidationSettings


def build_default_checks(
    registry: ModuleRegistryPort,
    settings: PlanValidationSettings,
    error_factory: PlanValidationErrorFactory | None = None,
) -> tuple[PlanCheck, ...]:
    """Build the standard validation pipeline in execution order."""
    factory = error_factory or PlanValidationErrorFactory()
    policy = OperationPolicy(registry, factory)
    path_value_validator = PathValueValidator(settings, factory)
    return (
        SchemaValidator(factory),
        RegistryEntryValidator(policy, factory),
        ArgumentValidator(policy, path_value_validator, factory),
        PlanPathValidator(policy, path_value_validator),
        LimitsValidator(settings, factory),
        SecurityValidator(settings, factory),
        ApprovalValidator(policy, factory),
    )
