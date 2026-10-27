"""Registry helper functions."""

from collections.abc import Sequence

from domain.entities.registry import RegistrySnapshot
from infrastructure.registry.catalog import MODULE_SPECS
from infrastructure.registry.constants import REGISTRY_VERSION
from infrastructure.registry.validators import RegistrySnapshotBuilder


def build_snapshot(specs: Sequence = MODULE_SPECS) -> RegistrySnapshot:
    """Build a registry snapshot from module specifications."""
    builder = RegistrySnapshotBuilder()
    return builder.build_snapshot(specs, registry_version=REGISTRY_VERSION)
