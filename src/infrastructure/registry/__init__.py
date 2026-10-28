"""Static module registry."""

from infrastructure.registry.catalog import (
    ALLOWED_MODULE_PREFIX,
    MODULE_FUNCTIONS,
    MODULE_SPECS,
    OUTPUT_DESCRIPTION,
    REGISTRY_VERSION,
    ModuleSpec,
)
from infrastructure.registry.functions import build_snapshot
from infrastructure.registry.module_registry import (
    ModuleRegistry,
    build_module_registry,
)
from infrastructure.registry.validators import (
    DependencyValidator,
    ExampleValidator,
    ModuleMetadataBuilder,
    RegistrySnapshotBuilder,
    RegistryValidator,
    SignatureValidator,
    TypeValidator,
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
    "ModuleRegistry",
    "ModuleSpec",
    "RegistrySnapshotBuilder",
    "RegistryValidator",
    "SignatureValidator",
    "TypeValidator",
    "build_module_registry",
    "build_snapshot",
]
