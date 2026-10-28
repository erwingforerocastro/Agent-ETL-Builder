"""Backward-compatible registry catalog exports."""

from application.registry.constants import (
    ALLOWED_MODULE_PREFIX,
    OUTPUT_DESCRIPTION,
    REGISTRY_VERSION,
)
from application.registry.specs import MODULE_SPECS, ModuleSpec
from infrastructure.registry.bindings import MODULE_FUNCTIONS
from infrastructure.registry.functions import build_snapshot
from infrastructure.registry.validators import (
    DependencyValidator,
    ExampleValidator,
    ModuleMetadataBuilder,
    RegistrySnapshotBuilder,
    RegistryValidator,
    SignatureValidator,
    TypeValidator,
    _annotation_to_text,
    _format_default,
    _metadata_for,
    _registry_error,
    _validate_default,
    _validate_dependencies,
    _validate_example_value,
    _validate_examples,
    _value_matches_type,
)

__all__ = [
    "ALLOWED_MODULE_PREFIX",
    "MODULE_FUNCTIONS",
    "MODULE_SPECS",
    "OUTPUT_DESCRIPTION",
    "REGISTRY_VERSION",
    "DependencyValidator",
    "ExampleValidator",
    "ModuleMetadataBuilder",
    "ModuleSpec",
    "RegistrySnapshotBuilder",
    "RegistryValidator",
    "SignatureValidator",
    "TypeValidator",
    "_annotation_to_text",
    "_format_default",
    "_metadata_for",
    "_registry_error",
    "_validate_default",
    "_validate_dependencies",
    "_validate_example_value",
    "_validate_examples",
    "_value_matches_type",
    "build_snapshot",
]
