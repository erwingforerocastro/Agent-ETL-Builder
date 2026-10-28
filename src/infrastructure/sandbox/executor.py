"""Sandboxed executor."""

import signal
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from types import FrameType
from typing import Any, cast

from infrastructure.sandbox.limits import SandboxLimits


class SandboxTimeoutError(Exception):
    pass


class SandboxViolationError(Exception):
    pass


@contextmanager
def timeout_context(seconds: float) -> Iterator[None]:
    if seconds <= 0:
        yield
        return

    # SIGALRM is not available on Windows; the caller still gets a bounded run
    # through the interpreter/workflow timeout once that layer is implemented.
    sigalrm = getattr(signal, "SIGALRM", None)
    alarm = getattr(signal, "alarm", None)
    if sigalrm is None or alarm is None:
        yield
        return

    def handler(signum: int, frame: FrameType | None) -> None:
        raise SandboxTimeoutError("Execution timed out")

    alarm_fn = cast(Callable[[int], int], alarm)
    old_handler = signal.signal(cast(int, sigalrm), handler)
    alarm_fn(int(seconds))
    try:
        yield
    finally:
        alarm_fn(0)
        signal.signal(cast(int, sigalrm), old_handler)


class SandboxExecutor:
    def __init__(self, limits: SandboxLimits | None = None) -> None:
        self.limits = limits or SandboxLimits()

    def run(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        with timeout_context(self.limits.timeout_seconds):
            return func(*args, **kwargs)
