"""Configuration shared by plan validation checks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PlanValidationSettings:
    """Limits and workspace constraints enforced while validating a plan."""

    workspace_root: Path
    max_steps: int = 100
    max_chunk_size: int = 10_000_000
    max_plan_bytes: int = 1_000_000
    max_path_length: int = 260
    max_param_depth: int = 10
    max_string_length: int = 10_000
