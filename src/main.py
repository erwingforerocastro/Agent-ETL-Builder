"""Application composition root."""

from pathlib import Path

from application.registry.specs import MODULE_SPECS
from application.use_cases.execute_plan import ExecutePlanUseCase
from application.validation.operations import OperationPolicy
from application.validation.plan_validator import PlanValidator
from domain.entities.run import WorkflowLimits
from infrastructure.approval.in_memory import InMemoryApprovalGateway
from infrastructure.cleanup.filesystem import FilesystemCleanup
from infrastructure.clock import SystemClock
from infrastructure.config.settings import Settings
from infrastructure.interpreter.step_runner import SandboxStepRunner
from infrastructure.registry.bindings import MODULE_FUNCTIONS
from infrastructure.registry.module_registry import build_module_registry
from infrastructure.sandbox.executor import SandboxExecutor
from infrastructure.sandbox.limits import SandboxLimits
from infrastructure.state.checkpointing import create_in_memory_checkpointer
from infrastructure.state.run_checkpoint import InMemoryRunCheckpoint
from infrastructure.validation.path_probe import FilesystemWorkspaceProbe
from infrastructure.validation.plan_hasher import JsonPlanHasher
from infrastructure.validation.plan_sizer import JsonPlanSizer
from interfaces.api.app import create_app

workspace = Path.cwd()
settings = Settings.from_env()
checkpointer = create_in_memory_checkpointer()
module_registry = build_module_registry(MODULE_SPECS, MODULE_FUNCTIONS)
plan_validator = PlanValidator(
    module_registry,
    workspace=FilesystemWorkspaceProbe(workspace),
    sizer=JsonPlanSizer(),
)
sandbox = SandboxExecutor(SandboxLimits(), workspace=workspace)
step_runner = SandboxStepRunner(module_registry, sandbox)
execute_plan = ExecutePlanUseCase(step_runner, plan_validator)
clock = SystemClock()
run_checkpoint = InMemoryRunCheckpoint()
approval_gateway = InMemoryApprovalGateway(clock)
cleanup = FilesystemCleanup(workspace / "artifacts")
plan_hasher = JsonPlanHasher()
approval_policy = OperationPolicy(module_registry)
workflow_limits = WorkflowLimits(
    approval_timeout_seconds=settings.approval_timeout_seconds,
    cleanup_policy=settings.cleanup_policy,
)
app = create_app(service_name=settings.service_name, version=settings.version)
app.state.checkpointer = checkpointer
app.state.module_registry = module_registry
app.state.plan_validator = plan_validator
app.state.execute_plan = execute_plan
app.state.run_checkpoint = run_checkpoint
app.state.approval_gateway = approval_gateway
app.state.cleanup = cleanup
app.state.plan_hasher = plan_hasher
app.state.approval_policy = approval_policy
app.state.workflow_limits = workflow_limits
