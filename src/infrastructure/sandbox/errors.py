"""Structured errors raised by the execution sandbox."""

from collections.abc import Mapping

from domain.errors import SandboxError


class SandboxTimeoutError(SandboxError):
    """Execution exceeded the wall-clock limit."""

    def __init__(
        self,
        *,
        message: str = "Execution exceeded the wall-clock limit",
        context: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(
            code="SANDBOX_TIMEOUT",
            message=message,
            module=__name__,
            context=context,
        )


class SandboxMemoryError(SandboxError):
    """Execution exceeded the memory limit."""

    def __init__(
        self,
        *,
        message: str = "Execution exceeded the memory limit",
        context: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(
            code="SANDBOX_MEMORY_LIMIT",
            message=message,
            module=__name__,
            context=context,
        )


class SandboxViolationError(SandboxError):
    """Execution attempted an operation forbidden by sandbox policy."""

    def __init__(
        self,
        *,
        code: str = "SANDBOX_VIOLATION",
        message: str = "Execution attempted a forbidden operation",
        context: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(
            code=code,
            message=message,
            module=__name__,
            context=context,
        )


class SandboxExecutionError(SandboxError):
    """Sandboxed execution failed before producing a result."""

    def __init__(
        self,
        *,
        code: str = "SANDBOX_EXECUTION_FAILED",
        message: str = "Sandboxed execution failed",
        context: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(
            code=code,
            message=message,
            module=__name__,
            context=context,
        )


__all__ = [
    "SandboxError",
    "SandboxExecutionError",
    "SandboxMemoryError",
    "SandboxTimeoutError",
    "SandboxViolationError",
]
