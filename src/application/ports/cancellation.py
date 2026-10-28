"""Cancellation contract shared by workflow and execution."""

from typing import Protocol


class CancellationTokenPort(Protocol):
    def cancel(self) -> None: ...

    def is_cancelled(self) -> bool: ...
