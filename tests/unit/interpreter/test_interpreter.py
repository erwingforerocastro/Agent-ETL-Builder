"""Unit tests for interpreter."""

from pathlib import Path

import pytest

from application.registry.specs import MODULE_SPECS
from application.use_cases.execute_plan import ExecutePlanUseCase
from domain.entities.plan import (
    ExecutionPlan,
    PlanChunking,
    PlanDestination,
    PlanSource,
    PlanTransformation,
)
from infrastructure.interpreter.step_runner import SandboxStepRunner
from infrastructure.registry.bindings import MODULE_FUNCTIONS
from infrastructure.registry.module_registry import build_module_registry
from infrastructure.sandbox import SandboxExecutor, SandboxLimits
from infrastructure.validation.path_probe import FilesystemWorkspaceProbe
from infrastructure.validation.plan_sizer import JsonPlanSizer
from infrastructure.validation.plan_validator import PlanValidator


def test_interpreter_executes_valid_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    registry = build_module_registry(MODULE_SPECS, MODULE_FUNCTIONS)
    sandbox = SandboxExecutor(SandboxLimits(timeout_seconds=0), workspace=tmp_path)
    validator = PlanValidator(
        registry,
        workspace=FilesystemWorkspaceProbe(tmp_path),
        sizer=JsonPlanSizer(),
    )
    use_case = ExecutePlanUseCase(
        SandboxStepRunner(registry, sandbox),
        validator,
    )
    input_file = tmp_path / "input.csv"
    input_file.write_text("name\n Ada \nBob\n", encoding="utf-8")
    output_file = tmp_path / "output.csv"
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

    result = use_case.execute(plan)

    assert result.status == "success"
    assert output_file.exists()
