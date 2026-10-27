"""Static module registry."""

from infrastructure.registry.catalog import (
    ALLOWED_MODULE_PREFIX,
    MODULE_SPECS,
    ModuleSpec,
    OUTPUT_DESCRIPTION,
    REGISTRY_VERSION,
)
from infrastructure.registry.constants import (
    ALLOWED_MODULE_PREFIX as ALLOWED_MODULE_PREFIX,
    OUTPUT_DESCRIPTION as OUTPUT_DESCRIPTION,
    REGISTRY_VERSION as REGISTRY_VERSION,
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
    "DependencyValidator",
    "ExampleValidator",
    "MODULE_SPECS",
    "ModuleMetadataBuilder",
    "ModuleRegistry",
    "ModuleSpec",
    "OUTPUT_DESCRIPTION",
    "REGISTRY_VERSION",
    "RegistrySnapshotBuilder",
    "RegistryValidator",
    "SignatureValidator",
    "TypeValidator",
    "build_module_registry",
    "build_snapshot",
]

