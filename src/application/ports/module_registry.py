"""Application-facing module registry contract."""

from typing import Protocol

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

    def ensure_version(self, expected_version: str) -> None: ...
