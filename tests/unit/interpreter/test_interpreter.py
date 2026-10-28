"""Unit tests for interpreter."""

from pathlib import Path

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


def test_interpreter_executes_valid_plan(tmp_path: Path) -> None:
    registry = build_module_registry(MODULE_SPECS, MODULE_FUNCTIONS)
    use_case = ExecutePlanUseCase(SandboxStepRunner(registry))
    input_file = tmp_path / "input.csv"
    input_file.write_text("name\n Ada \nBob\n", encoding="utf-8")
    output_file = tmp_path / "output.csv"
    plan = ExecutionPlan(
        plan_version="1.0",
        mode="pipeline",
        run_id="123-abc",
        name="test",
        description="test plan",
        source=PlanSource(operation="read_csv", params={"path": str(input_file)}),
        transformations=[
            PlanTransformation(
                step_id="s1",
                operation="trim_whitespace",
                params={"columns": ["name"]},
            )
        ],
        destination=PlanDestination(operation="save_csv", params={"path": str(output_file)}),
        chunking=PlanChunking(enabled=True, size=1000),
        on_error="fail_fast",
        approval_required=False,
    )
    result = use_case.execute(plan)
    assert result.status == "success"
    assert output_file.exists()
