"""Sandbox limits."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SandboxLimits:
    timeout_seconds: float = 60.0
    memory_mb: int = 512
    max_cpu_percent: int = 80
    allow_network: bool = False
    workspace_only: bool = True
