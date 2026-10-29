"""Application policy for registry error construction."""

from __future__ import annotations

from collections.abc import Mapping

from domain.errors import RegistryError


class RegistryErrorFactory:
    """Builds structured errors for registry validation."""

    def create_error(
        self,
        *,
        code: str,
        message: str,
        context: Mapping[str, object] | None = None,
        module_name: str | None = None,
    ) -> RegistryError:
        return RegistryError(
            code=code,
            message=message,
            module=module_name or __name__,
            context=context,
        )


__all__ = ["RegistryErrorFactory"]
