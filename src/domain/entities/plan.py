"""Plan entities and value objects."""

from collections.abc import Mapping
from dataclasses import dataclass


def _require_text(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must not be blank")


def _require_non_negative_int(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")


def _require_positive_int(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")


@dataclass(frozen=True, slots=True)
class PlanSource:
    operation: str
    params: Mapping[str, object]

    def __post_init__(self) -> None:
        _require_text(self.operation, "source operation")
        object.__setattr__(self, "params", dict(self.params))


@dataclass(frozen=True, slots=True)
class PlanDestination:
    operation: str
    params: Mapping[str, object]

    def __post_init__(self) -> None:
        _require_text(self.operation, "destination operation")
        object.__setattr__(self, "params", dict(self.params))


@dataclass(frozen=True, slots=True)
class PlanTransformation:
    step_id: str
    operation: str
    params: Mapping[str, object]

    def __post_init__(self) -> None:
        _require_text(self.step_id, "step_id")
        _require_text(self.operation, "operation")
        object.__setattr__(self, "params", dict(self.params))


@dataclass(frozen=True, slots=True)
class PlanChunking:
    enabled: bool
    size: int

    def __post_init__(self) -> None:
        _require_positive_int(self.size, "chunk size")


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    plan_version: str
    mode: str
    run_id: str
    name: str
    description: str
    source: PlanSource | None
    transformations: tuple[PlanTransformation, ...]
    destination: PlanDestination | None
    chunking: PlanChunking
    on_error: str
    approval_required: bool

    def __post_init__(self) -> None:
        _require_text(self.plan_version, "plan_version")
        _require_text(self.mode, "mode")
        _require_text(self.run_id, "run_id")
        _require_text(self.name, "name")
        _require_text(self.description, "description")
        _require_text(self.on_error, "on_error")
        if self.mode not in {"pipeline", "assessment"}:
            raise ValueError("mode must be 'pipeline' or 'assessment'")
        if self.mode == "assessment":
            if self.destination is not None:
                raise ValueError("assessment plans must not have a destination")
        elif self.mode == "pipeline":
            if self.source is None:
                raise ValueError("pipeline plans must have a source")
            if self.destination is None:
                raise ValueError("pipeline plans must have a destination")
        step_ids = [step.step_id for step in self.transformations]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("step_id values must be unique")
        object.__setattr__(self, "transformations", tuple(self.transformations))
