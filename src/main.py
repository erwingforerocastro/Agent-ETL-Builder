"""Application composition root."""

from pathlib import Path

from application.assessment.assess_source import AssessSourceUseCase
from application.planning.intake import NaturalLanguagePlanIntakeFactory
from application.registry.specs import MODULE_SPECS
from application.use_cases.execute_plan import ExecutePlanUseCase
from application.use_cases.profile_source import ProfileSourceUseCase
from application.use_cases.run_manager import RunManager
from application.use_cases.run_workflow_factory import RunWorkflowFactory
from application.validation.plan_validator import PlanValidator
from domain.entities.run import WorkflowLimits
from infrastructure.approval.in_memory import InMemoryApprovalGateway
from infrastructure.assessment.intake import AssessmentPlanIntakeFactory
from infrastructure.assessment.source_reader import WorkspaceSourceReader
from infrastructure.cancellation import EventCancellationToken
from infrastructure.cleanup.filesystem import FilesystemCleanup
from infrastructure.clock import SystemClock
from infrastructure.config.settings import Settings
from infrastructure.database.config import PostgresConfig
from infrastructure.database.postgres import PostgresDatabase
from infrastructure.interpreter.registry_step_runner import RegistryStepRunner
from infrastructure.loaders.postgresql import PostgresTableLoader
from infrastructure.logging.jsonl import JsonlRunLog
from infrastructure.logging.run_log import InMemoryRunLog
from infrastructure.logging.transform_csv import CsvTransformLog
from infrastructure.planning.ollama import OllamaPlanSynthesizer
from infrastructure.planning.source_schema import WorkspaceSourceSchemaProbe
from infrastructure.planning.submitted import SubmittedPlanIntakeFactory
from infrastructure.profiling.artifacts import FilesystemProfileWriter
from infrastructure.profiling.pandas_profiler import PandasChunkProfiler
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
postgres_loader = PostgresTableLoader(database) if database is not None else None
module_registry = build_module_registry(MODULE_SPECS, MODULE_FUNCTIONS)
workspace_probe = FilesystemWorkspaceProbe(workspace)
plan_validator = PlanValidator(
    module_registry,
    workspace=workspace_probe,
    sizer=CanonicalPlanSizer(),
)
sandbox = SandboxExecutor(SandboxLimits(), workspace=workspace)
step_runner = RegistryStepRunner(module_registry, sandbox)
run_log = JsonlRunLog(
    InMemoryRunLog(),
    logs_root=workspace / "logs",
)
transform_log = CsvTransformLog(artifacts_root=workspace / "artifacts")
execute_plan = ExecutePlanUseCase(
    step_runner,
    plan_validator,
    run_log=run_log,
    transform_log=transform_log,
)
profile_writer = FilesystemProfileWriter(workspace / "artifacts")
profile_source = ProfileSourceUseCase(PandasChunkProfiler(), profile_writer)
source_reader = WorkspaceSourceReader(workspace_probe)
source_schema_probe = WorkspaceSourceSchemaProbe(source_reader)
assessment = AssessSourceUseCase(source_reader, profile_source, sandbox=sandbox)
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
run_scheduler = ThreadPoolRunScheduler(max_workers=4)
plan_parser = PydanticPlanParser()
ollama_synthesizer = (
    OllamaPlanSynthesizer(
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        timeout_seconds=settings.ollama_timeout_seconds,
        snapshot=module_registry.snapshot(),
    )
    if settings.ollama_model is not None
    else None
)
nl_intake_factory = (
    NaturalLanguagePlanIntakeFactory(
        synthesizer=ollama_synthesizer,
        parser=plan_parser,
        schema_probe=source_schema_probe,
    )
    if ollama_synthesizer is not None
    else None
)
run_manager = RunManager(
    workflow_factory=run_workflow_factory,
    plan_parser=plan_parser,
    validator=plan_validator,
    intake_factory=SubmittedPlanIntakeFactory(),
    checkpoints=run_checkpoint,
    run_log=run_log,
    scheduler=run_scheduler,
    clock=clock,
    cancellation_factory=EventCancellationToken,
    assessment_intake_factory=AssessmentPlanIntakeFactory(assessment),
    nl_intake_factory=nl_intake_factory,
)
shutdown_callbacks = [run_scheduler.shutdown]
if ollama_synthesizer is not None:
    shutdown_callbacks.append(ollama_synthesizer.close)
app = create_app(
    service_name=settings.service_name,
    version=settings.version,
    run_manager=run_manager,
    max_request_bytes=settings.max_request_bytes,
    api_key=settings.api_key,
    shutdown_callbacks=tuple(shutdown_callbacks),
)
app.state.module_registry = module_registry
app.state.database = database
app.state.postgres_loader = postgres_loader
app.state.plan_validator = plan_validator
app.state.execute_plan = execute_plan
app.state.profile_writer = profile_writer
app.state.profile_source = profile_source
app.state.assessment = assessment
app.state.source_schema_probe = source_schema_probe
app.state.run_checkpoint = run_checkpoint
app.state.approval_gateway = approval_gateway
app.state.cleanup = cleanup
app.state.plan_hasher = plan_hasher
app.state.workflow_limits = workflow_limits
app.state.run_log = run_log
app.state.transform_log = transform_log
app.state.run_scheduler = run_scheduler
app.state.ollama_synthesizer = ollama_synthesizer
app.state.nl_intake_factory = nl_intake_factory
