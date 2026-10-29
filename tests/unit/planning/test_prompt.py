"""Unit tests for natural-language plan prompts."""

from __future__ import annotations

from application.planning.models import SourceSchema
from application.planning.prompt import PlanPromptBuilder
from application.registry.specs import MODULE_SPECS
from domain.entities.run import PlanRequest
from domain.errors import PlanValidationError
from infrastructure.registry.bindings import MODULE_FUNCTIONS
from infrastructure.registry.module_registry import build_module_registry

SNAPSHOT = build_module_registry(MODULE_SPECS, MODULE_FUNCTIONS).snapshot()


def _request() -> PlanRequest:
    return PlanRequest(
        run_id="run-1",
        thread_id="thread-1",
        message="Remove duplicates and trim whitespace",
        source="input.csv",
        destination="output.json",
    )


def test_system_prompt_contains_registry_rules_and_paths() -> None:
    prompt = PlanPromptBuilder(SNAPSHOT).system_prompt(
        source="input.csv",
        destination="output.json",
    )

    assert "Source path (fixed): input.csv" in prompt
    assert "Destination path (fixed): output.json" in prompt
    assert "drop_duplicate_rows" in prompt
    assert "trim_whitespace" in prompt
    assert "Never add extra parameters" in prompt
    assert "Do not invent column names" in prompt
    assert "Return only JSON" in prompt


def test_system_prompt_includes_authoritative_source_columns() -> None:
    prompt = PlanPromptBuilder(SNAPSHOT).system_prompt(
        source="input.csv",
        destination="output.json",
        source_schema=SourceSchema(
            columns=("name", "email"),
            dtypes=("string", "string"),
        ),
    )

    assert "Source columns (authoritative): name, email" in prompt
    assert "Source dtypes: string, string" in prompt
    assert "Never invent a column" in prompt


def test_system_prompt_includes_previous_validation_error() -> None:
    error = PlanValidationError(
        code="PLAN_INVALID_ARGUMENT",
        message="column must not be blank",
        module="test",
        context={"path": "transformations[0].column"},
    )

    prompt = PlanPromptBuilder(SNAPSHOT).system_prompt(
        source="input.csv",
        destination="output.json",
        previous_error=error,
    )

    assert "PLAN_INVALID_ARGUMENT" in prompt
    assert "column must not be blank" in prompt
    assert "transformations[0].column" in prompt


def test_messages_include_history_and_append_missing_user_message() -> None:
    builder = PlanPromptBuilder(SNAPSHOT)

    messages = builder.messages(
        _request(),
        history=(("assistant", "Which destination?"),),
    )

    assert messages[0]["role"] == "system"
    assert messages[1] == {"role": "assistant", "content": "Which destination?"}
    assert messages[-1] == {
        "role": "user",
        "content": "Remove duplicates and trim whitespace",
    }


def test_messages_do_not_duplicate_an_existing_user_message() -> None:
    builder = PlanPromptBuilder(SNAPSHOT)

    messages = builder.messages(
        _request(),
        history=(("user", "Remove duplicates and trim whitespace"),),
    )

    assert sum(message["role"] == "user" for message in messages) == 1
