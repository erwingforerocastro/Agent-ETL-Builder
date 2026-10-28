"""Sandbox limits."""

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SandboxLimits:
    """Resource and access limits applied to one sandboxed execution.

    A zero ``timeout_seconds`` or ``memory_mb`` disables that check.
    ``max_cpu_percent`` is kept for OS-level sandbox profiles; an in-process
    Python guard cannot enforce a CPU quota.
    """

    timeout_seconds: float = 60.0
    memory_mb: int = 512
    max_cpu_percent: int = 80
    allow_network: bool = False
    workspace_only: bool = True

    def __post_init__(self) -> None:
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds < 0:
            raise ValueError("timeout_seconds must be a finite non-negative number")
        if self.memory_mb < 0:
            raise ValueError("memory_mb must be non-negative")
        if not 0 <= self.max_cpu_percent <= 100:
            raise ValueError("max_cpu_percent must be between 0 and 100")


__all__ = ["SandboxLimits"]
