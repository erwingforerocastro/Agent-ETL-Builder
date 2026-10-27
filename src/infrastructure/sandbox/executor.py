"""Sandboxed executor."""

import signal
from contextlib import contextmanager
from typing import Any, Callable

from infrastructure.sandbox.limits import SandboxLimits


class SandboxTimeoutError(Exception):
    pass


class SandboxViolationError(Exception):
    pass


@contextmanager
def timeout_context(seconds: float):
    if seconds <= 0:
        yield
        return
    # Windows doesn't support SIGALRM the same way; use simple approach
    try:
        if hasattr(signal, "SIGALRM"):
            def handler(signum, frame):
                raise SandboxTimeoutError("Execution timed out")

            old_handler = signal.signal(signal.SIGALRM, handler)
            signal.alarm(int(seconds))
            try:
                yield
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)
        else:
            yield
    except Exception:
        yield


class SandboxExecutor:
    def __init__(self, limits: SandboxLimits | None = None) -> None:
        self.limits = limits or SandboxLimits()

    def run(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        if self.limits.timeout_seconds and hasattr(signal, "SIGALRM"):
            with timeout_context(self.limits.timeout_seconds):
                return func(*args, **kwargs)
        # On Windows or if no signal support, just run (limits would be enforced differently)
        return func(*args, **kwargs)
