"""Default dependency wiring for plan validation checks."""

from __future__ import annotations

from application.ports.module_registry import ModuleRegistryPort
from application.ports.workspace import WorkspaceProbePort
from application.validation.approval_validator import ApprovalValidator
from application.validation.argument_validator import ArgumentValidator
from application.validation.errors import PlanValidationErrorFactory
from application.validation.limits_validator import LimitsValidator
from application.validation.operations import OperationPolicy
from application.validation.path_validator import PathValueValidator, PlanPathValidator
from application.validation.plan_check import PlanCheck
from application.validation.registry_entry_validator import RegistryEntryValidator
from application.validation.schema_validator import SchemaValidator
from application.validation.security_validator import SecurityValidator
from application.validation.settings import PlanValidationSettings


def build_default_checks(
    registry: ModuleRegistryPort,
    settings: PlanValidationSettings,
    workspace: WorkspaceProbePort,
    error_factory: PlanValidationErrorFactory | None = None,
) -> tuple[PlanCheck, ...]:
    """Build the standard validation pipeline in execution order."""
    factory = error_factory or PlanValidationErrorFactory()
    policy = OperationPolicy(registry, factory)
    path_value_validator = PathValueValidator(settings, workspace, factory)
    return (
        SchemaValidator(factory),
        RegistryEntryValidator(policy, factory),
        ArgumentValidator(policy, path_value_validator, factory),
        PlanPathValidator(policy, path_value_validator),
        LimitsValidator(settings, factory),
        SecurityValidator(settings, factory),
        ApprovalValidator(policy, factory),
    )
