from importlib.metadata import version

from langgraph.checkpoint.memory import InMemorySaver

import main
from application.use_cases.execute_plan import ExecutePlanUseCase
from application.validation.plan_validator import PlanValidator


def test_composition_root_configures_app() -> None:
    assert main.app.title == main.settings.service_name
    assert main.app.version == version("agent-etl-builder")


def test_composition_root_wires_one_process_local_checkpointer() -> None:
    assert isinstance(main.checkpointer, InMemorySaver)
    assert main.app.state.checkpointer is main.checkpointer


def test_composition_root_wires_the_module_registry() -> None:
    assert main.app.state.module_registry is main.module_registry
    assert main.module_registry.snapshot().version == "1.0.0"


def test_composition_root_wires_plan_validation_and_execution() -> None:
    assert isinstance(main.plan_validator, PlanValidator)
    assert isinstance(main.execute_plan, ExecutePlanUseCase)
    assert main.app.state.plan_validator is main.plan_validator
    assert main.app.state.execute_plan is main.execute_plan
