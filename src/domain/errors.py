"""Shared ETL error contracts."""

from collections.abc import Mapping


class EtlError(Exception):
    """Base error with stable, redaction-ready metadata."""

    code: str
    message: str
    module: str
    retryable: bool
    context: dict[str, object]

    def __init__(
        self,
        *,
        code: str,
        message: str,
        module: str,
        retryable: bool = False,
        context: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.module = module
        self.retryable = retryable
        self.context = dict(context or {})

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "type": type(self).__name__,
            "module": self.module,
            "message": self.message,
            "retryable": self.retryable,
            "context": dict(self.context),
        }


class TransformationError(EtlError):
    """A deterministic data transformation failed."""


class RegistryError(EtlError):
    """The module registry is invalid or a lookup failed."""
