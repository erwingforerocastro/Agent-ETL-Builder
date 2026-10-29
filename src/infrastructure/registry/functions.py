"""Registry snapshot assembly."""

from collections.abc import Callable, Mapping, Sequence

import pandas as pd

from application.registry.constants import REGISTRY_VERSION
from application.registry.metadata import RegistryErrorFactory
from application.registry.specs import ModuleSpec
from domain.entities.registry import RegistrySnapshot
from infrastructure.registry.validators import ModuleMetadataBuilder


def build_snapshot(
    specs: Sequence[ModuleSpec],
    functions: Mapping[str, Callable[..., pd.DataFrame]],
    registry_version: str = REGISTRY_VERSION,
) -> RegistrySnapshot:
    """Build a registry snapshot from specs and their bound callables."""
    error_factory = RegistryErrorFactory()
    names = [spec.name for spec in specs]
    _reject_duplicate_names(names, error_factory)
    _require_function_for_every_spec(names, functions, error_factory)
    _reject_unbound_functions(names, functions, error_factory)

    builder = ModuleMetadataBuilder(error_factory)
    modules = tuple(builder.metadata_for(spec, functions[spec.name]) for spec in specs)
    return RegistrySnapshot(version=registry_version, modules=modules)


def _reject_duplicate_names(
    names: Sequence[str],
    error_factory: RegistryErrorFactory,
) -> None:
    if len(names) == len(set(names)):
        return
    duplicates = sorted({name for name in names if names.count(name) > 1})
    raise error_factory.create_error(
        code="REGISTRY_DUPLICATE_MODULE",
        message="Registry contains duplicate module names",
        context={"modules": duplicates},
        module_name=__name__,
    )


def _require_function_for_every_spec(
    names: Sequence[str],
    functions: Mapping[str, Callable[..., pd.DataFrame]],
    error_factory: RegistryErrorFactory,
) -> None:
    missing = sorted(set(names) - set(functions))
    if missing:
        raise error_factory.create_error(
            code="REGISTRY_MISSING_FUNCTION",
            message="Registry spec has no bound callable",
            context={"modules": missing},
            module_name=__name__,
        )


def _reject_unbound_functions(
    names: Sequence[str],
    functions: Mapping[str, Callable[..., pd.DataFrame]],
    error_factory: RegistryErrorFactory,
) -> None:
    unknown = sorted(set(functions) - set(names))
    if unknown:
        raise error_factory.create_error(
            code="REGISTRY_UNKNOWN_FUNCTION",
            message="Registry contains a callable without a spec",
            context={"modules": unknown},
            module_name=__name__,
        )


__all__ = ["build_snapshot"]
