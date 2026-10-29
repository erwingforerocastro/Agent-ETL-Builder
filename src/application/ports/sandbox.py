"""Sandboxed callable execution contract used by infrastructure adapters."""

from collections.abc import Callable
from typing import Any, Protocol


class SandboxRunnerPort(Protocol):
    """Runs one callable under the configured sandbox guards."""

    def run(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any: ...


__all__ = ["SandboxRunnerPort"]
