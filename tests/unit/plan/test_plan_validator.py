"""Unit tests for plan validator."""

from pathlib import Path

import pytest

from application.ports.module_registry import ModuleRegistryPort
from domain.entities.plan import (
    ExecutionPlan,
    PlanChunking,
    PlanDestination,
    PlanSource,
    PlanTransformation,
)
from infrastructure.registry.module_registry import build_module_registry
from infrastructure.validation.plan_validator import PlanValidationError, PlanValidator


def test_plan_validator_accepts_valid_pipeline() -> None:
    registry = build_module_registry()
    validator = PlanValidator(registry, workspace_root=Path("."))
    plan = ExecutionPlan(
        plan_version="1.0",
        mode="pipeline",
        run_id="123-abc",
        name="test",
        description="test plan",
        source=PlanSource(operation="read_csv", params={"path": "input.csv"}),
        transformations=[
            PlanTransformation(
                step_id="s1",
                operation="trim_whitespace",
                params={"columns": ["name"]},
            )
        ],
        destination=PlanDestination(operation="save_csv", params={"path": "output.csv"}),
        chunking=PlanChunking(enabled=True, size=1000),
        on_error="fail_fast",
        approval_required=True,
    )
    validator.validate(plan)


def test_plan_validator_rejects_traversal() -> None:
    registry = build_module_registry()
    validator = PlanValidator(registry, workspace_root=Path("."))
    plan = ExecutionPlan(
        plan_version="1.0",
        mode="pipeline",
        run_id="123-abc",
        name="test",
        description="test plan",
        source=PlanSource(operation="read_csv", params={"path": "../etc/passwd"}),
        transformations=[],
        destination=PlanDestination(operation="save_csv", params={"path": "output.csv"}),
        chunking=PlanChunking(enabled=True, size=1000),
        on_error="fail_fast",
        approval_required=True,
    )
    with pytest.raises(PlanValidationError) as caught:
        validator.validate(plan)
    assert caught.value.code in {"PLAN_PATH_TRAVERSAL", "PLAN_PATH_OUTSIDE_WORKSPACE"}


def test_plan_validator_rejects_absolute_path() -> None:
    registry = build_module_registry()
    validator = PlanValidator(registry, workspace_root=Path("."))
    plan = ExecutionPlan(
        plan_version="1.0",
        mode="pipeline",
        run_id="123-abc",
        name="test",
        description="test plan",
        source=PlanSource(operation="read_csv", params={"path": "/etc/passwd"}),
        transformations=[],
        destination=PlanDestination(operation="save_csv", params={"path": "output.csv"}),
        chunking=PlanChunking(enabled=True, size=1000),
        on_error="fail_fast",
        approval_required=True,
    )
    with pytest.raises(PlanValidationError) as caught:
        validator.validate(plan)
    assert caught.value.code == "PLAN_PATH_NOT_ALLOWED"


def test_plan_validator_rejects_unknown_operation() -> None:
    registry = build_module_registry()
    validator = PlanValidator(registry, workspace_root=Path("."))
    plan = ExecutionPlan(
        plan_version="1.0",
        mode="pipeline",
        run_id="123-abc",
        name="test",
        description="test plan",
        source=PlanSource(operation="unknown_op", params={}),
        transformations=[],
        destination=PlanDestination(operation="save_csv", params={"path": "output.csv"}),
        chunking=PlanChunking(enabled=True, size=1000),
        on_error="fail_fast",
        approval_required=True,
    )
    with pytest.raises(PlanValidationError) as caught:
        validator.validate(plan)
    assert caught.value.code == "PLAN_UNKNOWN_OPERATION"


def test_plan_validator_rejects_duplicate_step_ids() -> None:
    registry = build_module_registry()
    with pytest.raises(ValueError):
        ExecutionPlan(
            plan_version="1.0",
            mode="pipeline",
            run_id="123-abc",
            name="test",
            description="test plan",
            source=PlanSource(operation="read_csv", params={"path": "input.csv"}),
            transformations=[
                PlanTransformation(step_id="s1", operation="trim_whitespace", params={}),
                PlanTransformation(step_id="s1", operation="trim_whitespace", params={}),
            ],
            destination=PlanDestination(operation="save_csv", params={"path": "output.csv"}),
            chunking=PlanChunking(enabled=True, size=1000),
            on_error="fail_fast",
            approval_required=True,
        )


def test_plan_validator_rejects_assessment_with_destination() -> None:
    with pytest.raises(ValueError):
        ExecutionPlan(
            plan_version="1.0",
            mode="assessment",
            run_id="123-abc",
            name="test",
            description="test plan",
            source=PlanSource(operation="read_csv", params={"path": "input.csv"}),
            transformations=[],
            destination=PlanDestination(operation="save_csv", params={"path": "output.csv"}),
            chunking=PlanChunking(enabled=True, size=1000),
            on_error="fail_fast",
            approval_required=False,
        )
