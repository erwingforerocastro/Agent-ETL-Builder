"""Sandbox limits."""

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SandboxLimits:
    """Resource and access limits applied to one sandboxed execution.

    A zero ``timeout_seconds`` or ``memory_mb`` disables that check. CPU
    quotas require OS-level isolation and are not part of the in-process guard.
    """

    timeout_seconds: float = 60.0
    memory_mb: int = 512
    allow_network: bool = False
    workspace_only: bool = True

    def __post_init__(self) -> None:
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds < 0:
            raise ValueError("timeout_seconds must be a finite non-negative number")
        if self.memory_mb < 0:
            raise ValueError("memory_mb must be non-negative")


__all__ = ["SandboxLimits"]
