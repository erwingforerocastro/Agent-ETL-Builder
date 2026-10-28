"""Static module registry infrastructure."""

from infrastructure.registry.bindings import (
    ALLOWED_MODULE_PREFIX,
    CAPABILITY_PACKAGES,
    MODULE_FUNCTIONS,
)
from infrastructure.registry.functions import build_snapshot
from infrastructure.registry.module_registry import (
    ModuleRegistry,
    build_module_registry,
)
from infrastructure.registry.validators import (
    DependencyValidator,
    ModuleMetadataBuilder,
    RegistrySnapshotBuilder,
    SignatureValidator,
)

__all__ = [
    "ALLOWED_MODULE_PREFIX",
    "CAPABILITY_PACKAGES",
    "MODULE_FUNCTIONS",
    "DependencyValidator",
    "ModuleMetadataBuilder",
    "ModuleRegistry",
    "RegistrySnapshotBuilder",
    "SignatureValidator",
    "build_module_registry",
    "build_snapshot",
]
