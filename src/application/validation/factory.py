"""Default dependency wiring for plan validation checks."""

from __future__ import annotations

from application.ports.module_registry import ModuleRegistryReadPort
from application.ports.plan_sizer import PlanSizerPort
from application.ports.workspace import WorkspaceProbePort
from application.validation.approval_validator import ApprovalValidator
from application.validation.argument_validator import ArgumentValidator
from application.validation.errors import PlanValidationErrorFactory
from application.validation.limits_validator import LimitsValidator
from application.validation.operation_role_validator import OperationRoleValidator
from application.validation.operations import OperationCatalog, OperationSafetyPolicy
from application.validation.path_validator import PathValueValidator, PlanPathValidator
from application.validation.plan_validation_check import PlanValidationCheck
from application.validation.registry_entry_validator import RegistryEntryValidator
from application.validation.schema_validator import SchemaValidator
from application.validation.security_validator import SecurityValidator
from application.validation.settings import PlanValidationSettings
from application.validation.transformation_contract_validator import (
    TransformationContractValidator,
)


def build_default_checks(
    registry: ModuleRegistryReadPort,
    settings: PlanValidationSettings,
    workspace: WorkspaceProbePort,
    sizer: PlanSizerPort,
    error_factory: PlanValidationErrorFactory | None = None,
) -> tuple[PlanValidationCheck, ...]:
    """Build the standard validation pipeline in execution order."""
    factory = error_factory or PlanValidationErrorFactory()
    catalog = OperationCatalog(registry, factory)
    safety = OperationSafetyPolicy()
    path_value_validator = PathValueValidator(settings, workspace, factory)
    return (
        SchemaValidator(factory),
        RegistryEntryValidator(catalog, safety, factory),
        OperationRoleValidator(catalog, factory),
        ArgumentValidator(catalog, path_value_validator, factory),
        TransformationContractValidator(catalog, factory),
        PlanPathValidator(catalog, path_value_validator),
        LimitsValidator(settings, sizer, factory),
        SecurityValidator(settings, factory),
        ApprovalValidator(catalog, safety, factory),
    )
