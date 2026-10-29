"""Golden-plan tests for the transformation DSL."""

from collections.abc import Sequence
from pathlib import Path

import pytest

from application.registry.specs import MODULE_SPECS
from domain.entities.plan import (
    ExecutionPlan,
    PlanChunking,
    PlanDestination,
    PlanSource,
    PlanTransformation,
)
from infrastructure.registry.bindings import MODULE_FUNCTIONS
from infrastructure.registry.module_registry import build_module_registry
from infrastructure.validation.path_probe import FilesystemWorkspaceProbe
from infrastructure.validation.plan_hasher import CanonicalPlanHasher
from infrastructure.validation.plan_sizer import CanonicalPlanSizer
from infrastructure.validation.plan_validator import PlanValidator


def _steps() -> tuple[PlanTransformation, ...]:
    return (
        PlanTransformation("s1", "drop_duplicate_rows", {"subset": ["id"]}),
        PlanTransformation("s2", "drop_empty_rows", {"subset": ["name"]}),
        PlanTransformation("s3", "trim_whitespace", {"columns": ["name"]}),
        PlanTransformation("s4", "change_text_case", {"columns": ["name"], "case": "upper"}),
        PlanTransformation(
            "s5",
            "cast_column",
            {"column": "amount", "target_type": "float", "errors": "coerce"},
        ),
        PlanTransformation("s6", "fill_missing_values", {"column": "amount", "method": "mean"}),
        PlanTransformation(
            "s7",
            "normalize_dates",
            {
                "column": "created_at",
                "output_format": "%Y-%m-%d",
                "errors": "coerce",
            },
        ),
        PlanTransformation(
            "s8", "replace_values", {"columns": ["status"], "old": "N/A", "new": None}
        ),
        PlanTransformation(
            "s9",
            "filter_rows",
            {"column": "created_at", "operator": "is_not_null"},
        ),
        PlanTransformation("s10", "standardize_column_names", {"case": "lower"}),
    )


def _plan(*, reverse: bool = False) -> ExecutionPlan:
    steps: Sequence[PlanTransformation] = _steps()
    if reverse:
        steps = tuple(reversed(steps))
    return ExecutionPlan(
        plan_version="1.0",
        mode="pipeline",
        run_id="1729850000000-a1b2c3d4",
        name="golden_transformations",
        description="Exercise every transformation category.",
        source=PlanSource(operation="read_csv", params={"path": "input.csv"}),
        transformations=steps,
        destination=PlanDestination(operation="save_csv", params={"path": "output.csv"}),
        chunking=PlanChunking(enabled=True, size=1000),
        on_error="fail_fast",
        approval_required=True,
    )


def _validator(workspace: Path) -> PlanValidator:
    return PlanValidator(
        build_module_registry(MODULE_SPECS, MODULE_FUNCTIONS),
        workspace=FilesystemWorkspaceProbe(workspace),
        sizer=CanonicalPlanSizer(),
    )


def test_golden_plan_validates_and_hashes_stably(tmp_path: Path) -> None:
    plan = _plan()
    hasher = CanonicalPlanHasher()

    _validator(tmp_path).validate(plan)

    assert hasher.hash(plan) == hasher.hash(_plan())


def test_reordering_steps_changes_the_plan_hash(tmp_path: Path) -> None:
    hasher = CanonicalPlanHasher()
    forward = _plan()
    reverse = _plan(reverse=True)

    _validator(tmp_path).validate(forward)
    _validator(tmp_path).validate(reverse)

    assert hasher.hash(forward) != hasher.hash(reverse)


def test_duplicate_step_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="step_id values must be unique"):
        ExecutionPlan(
            plan_version="1.0",
            mode="pipeline",
            run_id="1729850000000-a1b2c3d4",
            name="duplicate_steps",
            description="Duplicate step identifiers.",
            source=PlanSource(operation="read_csv", params={"path": "input.csv"}),
            transformations=(
                PlanTransformation("s1", "trim_whitespace", {"columns": ["name"]}),
                PlanTransformation("s1", "change_text_case", {"columns": ["name"]}),
            ),
            destination=PlanDestination(operation="save_csv", params={"path": "output.csv"}),
            chunking=PlanChunking(enabled=True, size=1000),
            on_error="fail_fast",
            approval_required=True,
        )
