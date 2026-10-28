"""Configuration shared by plan validation checks."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PlanValidationSettings:
    """Limits enforced while validating a plan."""

    max_steps: int = 100
    max_chunk_size: int = 10_000_000
    max_plan_bytes: int = 1_000_000
    max_path_length: int = 260
    max_param_depth: int = 10
    max_string_length: int = 10_000
