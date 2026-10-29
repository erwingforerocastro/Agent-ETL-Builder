"""Application composition root."""

from pathlib import Path

from application.registry.specs import MODULE_SPECS
from application.use_cases.execute_plan import ExecutePlanUseCase
from application.use_cases.run_manager import RunManager
from application.use_cases.run_workflow_factory import RunWorkflowFactory
from application.validation.plan_validator import PlanValidator
from domain.entities.run import WorkflowLimits
from infrastructure.approval.in_memory import InMemoryApprovalGateway
from infrastructure.cancellation import EventCancellationToken
from infrastructure.cleanup.filesystem import FilesystemCleanup
from infrastructure.clock import SystemClock
from infrastructure.config.settings import Settings
from infrastructure.database.config import PostgresConfig
from infrastructure.database.postgres import PostgresDatabase
from infrastructure.interpreter.registry_step_runner import RegistryStepRunner
from infrastructure.logging.run_log import InMemoryRunLog
from infrastructure.planning.submitted import SubmittedPlanIntakeFactory
from infrastructure.registry.bindings import MODULE_FUNCTIONS
from infrastructure.registry.module_registry import build_module_registry
from infrastructure.sandbox.executor import SandboxExecutor
from infrastructure.sandbox.limits import SandboxLimits
from infrastructure.scheduling.thread_pool import ThreadPoolRunScheduler
from infrastructure.state.run_checkpoint import InMemoryRunCheckpoint
from infrastructure.validation.path_probe import FilesystemWorkspaceProbe
from infrastructure.validation.plan_hasher import CanonicalPlanHasher
from infrastructure.validation.plan_parser import PydanticPlanParser
from infrastructure.validation.plan_sizer import CanonicalPlanSizer
from interfaces.api.app import create_app

workspace = Path.cwd()
settings = Settings.from_env()
database = (
    PostgresDatabase(
        PostgresConfig(
            dsn=settings.database_url,
            sslmode=settings.database_sslmode,
            sslrootcert=settings.database_sslrootcert,
            connect_timeout_seconds=settings.database_connect_timeout_seconds,
            statement_timeout_ms=settings.database_statement_timeout_ms,
            application_name=settings.database_application_name,
        )
    )
    if settings.database_url is not None
    else None
)
module_registry = build_module_registry(MODULE_SPECS, MODULE_FUNCTIONS)
plan_validator = PlanValidator(
    module_registry,
    workspace=FilesystemWorkspaceProbe(workspace),
    sizer=CanonicalPlanSizer(),
)
sandbox = SandboxExecutor(SandboxLimits(), workspace=workspace)
step_runner = RegistryStepRunner(module_registry, sandbox)
execute_plan = ExecutePlanUseCase(step_runner, plan_validator)
clock = SystemClock()
run_checkpoint = InMemoryRunCheckpoint()
approval_gateway = InMemoryApprovalGateway(clock)
cleanup = FilesystemCleanup(workspace / "artifacts")
plan_hasher = CanonicalPlanHasher()
workflow_limits = WorkflowLimits(
    approval_timeout_seconds=settings.approval_timeout_seconds,
    cleanup_policy=settings.cleanup_policy,
)
run_workflow_factory = RunWorkflowFactory(
    validator=plan_validator,
    executor=execute_plan,
    registry=module_registry,
    checkpoints=run_checkpoint,
    clock=clock,
    approvals=approval_gateway,
    cleanup=cleanup,
    hasher=plan_hasher,
    limits=workflow_limits,
)
run_log = InMemoryRunLog()
run_scheduler = ThreadPoolRunScheduler(max_workers=4)
run_manager = RunManager(
    workflow_factory=run_workflow_factory,
    plan_parser=PydanticPlanParser(),
    validator=plan_validator,
    intake_factory=SubmittedPlanIntakeFactory(),
    checkpoints=run_checkpoint,
    run_log=run_log,
    scheduler=run_scheduler,
    clock=clock,
    cancellation_factory=EventCancellationToken,
)
app = create_app(
    service_name=settings.service_name,
    version=settings.version,
    run_manager=run_manager,
    max_request_bytes=settings.max_request_bytes,
    api_key=settings.api_key,
    shutdown_callbacks=(run_scheduler.shutdown,),
)
app.state.module_registry = module_registry
app.state.database = database
app.state.plan_validator = plan_validator
app.state.execute_plan = execute_plan
app.state.run_checkpoint = run_checkpoint
app.state.approval_gateway = approval_gateway
app.state.cleanup = cleanup
app.state.plan_hasher = plan_hasher
app.state.workflow_limits = workflow_limits
app.state.run_log = run_log
app.state.run_scheduler = run_scheduler
