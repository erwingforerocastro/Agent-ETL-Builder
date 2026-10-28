"""Registry snapshot assembly."""

from collections.abc import Callable, Mapping, Sequence

import pandas as pd

from application.registry.constants import REGISTRY_VERSION
from application.registry.specs import ModuleSpec
from domain.entities.registry import RegistrySnapshot
from infrastructure.registry.validators import RegistrySnapshotBuilder


def build_snapshot(
    specs: Sequence[ModuleSpec],
    functions: Mapping[str, Callable[..., pd.DataFrame]],
) -> RegistrySnapshot:
    """Build a registry snapshot from specs and their bound callables."""
    builder = RegistrySnapshotBuilder()
    return builder.build_snapshot(
        specs,
        functions,
        registry_version=REGISTRY_VERSION,
    )


__all__ = ["build_snapshot"]
