"""Application-facing module registry contracts."""

from collections.abc import Callable
from typing import Any, Protocol

from domain.entities.registry import ModuleMetadata, RegistrySnapshot


class ModuleRegistryReadPort(Protocol):
    """Read-only access to registry metadata."""

    def snapshot(self) -> RegistrySnapshot: ...

    def get(
        self,
        name: str,
        *,
        version: str | None = None,
    ) -> ModuleMetadata | None: ...

    def require(
        self,
        name: str,
        *,
        version: str | None = None,
    ) -> ModuleMetadata: ...


class ModuleFunctionResolverPort(Protocol):
    """Resolves an allowlisted operation to its bound callable."""

    def function_for(
        self,
        name: str,
        *,
        version: str | None = None,
    ) -> Callable[..., Any]: ...


class ModuleRegistryPort(ModuleRegistryReadPort, ModuleFunctionResolverPort, Protocol):
    """Combined registry contract for consumers that need metadata and callables."""


__all__ = [
    "ModuleFunctionResolverPort",
    "ModuleRegistryPort",
    "ModuleRegistryReadPort",
]
