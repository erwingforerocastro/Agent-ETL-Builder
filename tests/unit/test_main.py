from importlib.metadata import version

import main
from application.assessment.assess_source import AssessSourceUseCase
from application.planning.intake import NaturalLanguagePlanIntakeFactory
from application.use_cases.execute_plan import ExecutePlanUseCase
from application.use_cases.profile_source import ProfileSourceUseCase
from application.use_cases.run_manager import RunManager
from application.validation.plan_validator import PlanValidator
from infrastructure.approval.in_memory import InMemoryApprovalGateway
from infrastructure.assessment.source_reader import WorkspaceSourceReader
from infrastructure.cleanup.filesystem import FilesystemCleanup
from infrastructure.database.postgres import PostgresDatabase
from infrastructure.loaders.postgresql import PostgresTableLoader
from infrastructure.logging.jsonl import JsonlRunLog
from infrastructure.logging.transform_csv import CsvTransformLog
from infrastructure.planning.ollama import OllamaPlanSynthesizer
from infrastructure.scheduling.thread_pool import ThreadPoolRunScheduler
from infrastructure.state.run_checkpoint import InMemoryRunCheckpoint
from infrastructure.validation.plan_hasher import CanonicalPlanHasher


def test_composition_root_configures_app() -> None:
    assert main.app.title == main.settings.service_name
    assert main.app.version == version("agent-etl-builder")


def test_composition_root_wires_the_module_registry() -> None:
    assert main.app.state.module_registry is main.module_registry
    assert main.module_registry.snapshot().version == "1.0.0"


def test_composition_root_wires_plan_validation_and_execution() -> None:
    assert isinstance(main.plan_validator, PlanValidator)
    assert isinstance(main.execute_plan, ExecutePlanUseCase)
    assert main.app.state.plan_validator is main.plan_validator
    assert main.app.state.execute_plan is main.execute_plan


def test_composition_root_wires_workflow_adapters() -> None:
    assert isinstance(main.run_checkpoint, InMemoryRunCheckpoint)
    assert isinstance(main.approval_gateway, InMemoryApprovalGateway)
    assert isinstance(main.cleanup, FilesystemCleanup)
    assert isinstance(main.plan_hasher, CanonicalPlanHasher)
    assert main.app.state.run_checkpoint is main.run_checkpoint
    assert main.app.state.approval_gateway is main.approval_gateway
    assert main.app.state.cleanup is main.cleanup
    assert main.app.state.plan_hasher is main.plan_hasher
    assert (
        main.app.state.workflow_limits.approval_timeout_seconds
        == main.settings.approval_timeout_seconds
    )


def test_composition_root_wires_the_run_api() -> None:
    assert isinstance(main.run_manager, RunManager)
    assert isinstance(main.run_log, JsonlRunLog)
    assert isinstance(main.transform_log, CsvTransformLog)
    assert isinstance(main.run_scheduler, ThreadPoolRunScheduler)
    assert main.app.state.run_manager is main.run_manager
    assert main.app.state.run_log is main.run_log
    assert main.app.state.transform_log is main.transform_log
    assert main.app.state.run_scheduler is main.run_scheduler
    assert main.app.state.ollama_synthesizer is main.ollama_synthesizer
    assert main.app.state.nl_intake_factory is main.nl_intake_factory
    if main.settings.ollama_model is None:
        assert main.ollama_synthesizer is None
        assert main.nl_intake_factory is None
    else:
        assert isinstance(main.ollama_synthesizer, OllamaPlanSynthesizer)
        assert isinstance(main.nl_intake_factory, NaturalLanguagePlanIntakeFactory)


def test_composition_root_wires_source_assessment() -> None:
    assert isinstance(main.profile_source, ProfileSourceUseCase)
    assert isinstance(main.source_reader, WorkspaceSourceReader)
    assert isinstance(main.assessment, AssessSourceUseCase)
    assert main.app.state.profile_source is main.profile_source
    assert main.app.state.profile_writer is main.profile_writer
    assert main.app.state.assessment is main.assessment


def test_composition_root_wires_the_optional_database_adapter() -> None:
    assert main.app.state.database is main.database
    assert main.app.state.postgres_loader is main.postgres_loader
    if main.settings.database_url is None:
        assert main.database is None
        assert main.postgres_loader is None
    else:
        assert isinstance(main.database, PostgresDatabase)
        assert isinstance(main.postgres_loader, PostgresTableLoader)
