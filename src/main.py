"""Application composition root."""

from pathlib import Path

from application.use_cases.execute_plan import ExecutePlanUseCase
from application.validation.plan_validator import PlanValidator
from infrastructure.config.settings import Settings
from infrastructure.interpreter.step_runner import SandboxStepRunner
from infrastructure.registry.module_registry import build_module_registry
from infrastructure.state.checkpointing import create_in_memory_checkpointer
from infrastructure.validation.path_probe import FilesystemWorkspaceProbe
from interfaces.api.app import create_app

settings = Settings.from_env()
checkpointer = create_in_memory_checkpointer()
module_registry = build_module_registry()
plan_validator = PlanValidator(
    module_registry,
    workspace=FilesystemWorkspaceProbe(Path.cwd()),
)
execute_plan = ExecutePlanUseCase(SandboxStepRunner(module_registry))
app = create_app(service_name=settings.service_name, version=settings.version)
app.state.checkpointer = checkpointer
app.state.module_registry = module_registry
app.state.plan_validator = plan_validator
app.state.execute_plan = execute_plan
