"""Application-facing module registry contract."""

from collections.abc import Callable
from typing import Any, Protocol

from domain.entities.registry import ModuleMetadata, RegistrySnapshot


class ModuleRegistryPort(Protocol):
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

    def function_for(
        self,
        name: str,
        *,
        version: str | None = None,
    ) -> Callable[..., Any]: ...

    def ensure_version(self, expected_version: str) -> None: ...
