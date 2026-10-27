"""Unit tests for interpreter."""

from pathlib import Path

import pandas as pd

from domain.entities.plan import (
    ExecutionPlan,
    PlanChunking,
    PlanDestination,
    PlanSource,
    PlanTransformation,
)
from infrastructure.interpreter.interpreter import PlanInterpreter
from infrastructure.registry.module_registry import build_module_registry


def test_interpreter_executes_valid_plan(tmp_path: Path) -> None:
    registry = build_module_registry()
    interpreter = PlanInterpreter(registry)
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
    result = interpreter.execute(plan)
    assert result["status"] == "success"
    assert output_file.exists()
