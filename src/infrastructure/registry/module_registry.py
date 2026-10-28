"""Versioned registry with an explicit callable allowlist."""

from collections.abc import Callable, Mapping, Sequence

import pandas as pd

from application.registry.specs import ModuleSpec
from domain.entities.registry import ModuleMetadata, RegistrySnapshot
from domain.errors import RegistryError
from infrastructure.registry.functions import build_snapshot


class ModuleRegistry:
    def __init__(
        self,
        *,
        snapshot: RegistrySnapshot,
        functions: Mapping[str, Callable[..., pd.DataFrame]],
    ) -> None:
        self._snapshot = snapshot
        self._functions = dict(functions)

    def snapshot(self) -> RegistrySnapshot:
        return self._snapshot

    def ensure_version(self, expected_version: str) -> None:
        if expected_version != self._snapshot.version:
            raise self._version_error(
                expected=expected_version,
                current=self._snapshot.version,
            )

    def get(
        self,
        name: str,
        *,
        version: str | None = None,
    ) -> ModuleMetadata | None:
        module = self._snapshot.get(name)
        if module is None:
            return None
        if version is not None and module.version != version:
            raise self._version_error(expected=version, current=module.version)
        return module

    def require(
        self,
        name: str,
        *,
        version: str | None = None,
    ) -> ModuleMetadata:
        module = self.get(name, version=version)
        if module is None:
            raise RegistryError(
                code="REGISTRY_UNKNOWN_MODULE",
                message="Requested module is not allowlisted",
                module=__name__,
                context={"module": name},
            )
        return module

    def function_for(
        self,
        name: str,
        *,
        version: str | None = None,
    ) -> Callable[..., pd.DataFrame]:
        self.require(name, version=version)
        return self._functions[name]

    def _version_error(self, *, expected: str, current: str) -> RegistryError:
        return RegistryError(
            code="REGISTRY_VERSION_MISMATCH",
            message="Registry or module version does not match",
            module=__name__,
            context={"expected": expected, "current": current},
        )


def build_module_registry(
    specs: Sequence[ModuleSpec],
    functions: Mapping[str, Callable[..., pd.DataFrame]],
) -> ModuleRegistry:
    return ModuleRegistry(
        snapshot=build_snapshot(specs, functions),
        functions=functions,
    )


__all__ = ["ModuleRegistry", "build_module_registry"]
