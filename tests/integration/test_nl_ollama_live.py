"""Optional live evaluation against a local Ollama model.

Enable with ``AGENT_ETL_TEST_OLLAMA=1`` and a running Ollama server.
"""

from __future__ import annotations

import os

import pytest

from application.planning.models import SourceSchema
from application.registry.specs import MODULE_SPECS
from domain.entities.run import PlanRequest
from infrastructure.planning.ollama import OllamaPlanSynthesizer
from infrastructure.registry.bindings import MODULE_FUNCTIONS
from infrastructure.registry.module_registry import build_module_registry

SNAPSHOT = build_module_registry(MODULE_SPECS, MODULE_FUNCTIONS).snapshot()
_SCHEMA = SourceSchema(
    columns=("name", "email", "status"),
    dtypes=("string", "string", "string"),
)


def _synthesizer() -> OllamaPlanSynthesizer:
    return OllamaPlanSynthesizer(
        model=os.getenv("AGENT_ETL_OLLAMA_MODEL", "llama3.1:8b"),
        base_url=os.getenv("AGENT_ETL_OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        timeout_seconds=120,
        snapshot=SNAPSHOT,
    )


def _request(message: str) -> PlanRequest:
    return PlanRequest(
        run_id="1729850000000-a1b2c3d4",
        thread_id="thread-live",
        message=message,
        source="input.csv",
        destination="output.json",
    )


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("AGENT_ETL_TEST_OLLAMA") != "1",
    reason="set AGENT_ETL_TEST_OLLAMA=1 to run the live Ollama evaluation",
)
def test_explicit_clean_request_selects_only_requested_operations() -> None:
    synthesizer = _synthesizer()
    try:
        draft = synthesizer.synthesize(
            _request("Remove duplicate rows and trim whitespace."),
            history=(("user", "Remove duplicate rows and trim whitespace."),),
            source_schema=_SCHEMA,
        )
    finally:
        synthesizer.close()

    operations = [step.operation for step in draft.transformations]
    assert "drop_duplicate_rows" in operations
    assert "trim_whitespace" in operations
    assert "filter_rows" not in operations
    assert "normalize_dates" not in operations
    assert not draft.questions


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("AGENT_ETL_TEST_OLLAMA") != "1",
    reason="set AGENT_ETL_TEST_OLLAMA=1 to run the live Ollama evaluation",
)
def test_vague_clean_request_does_not_add_destructive_steps() -> None:
    synthesizer = _synthesizer()
    try:
        draft = synthesizer.synthesize(
            _request("Clean the input file and save the result as JSON."),
            history=(("user", "Clean the input file and save the result as JSON."),),
            source_schema=_SCHEMA,
        )
    finally:
        synthesizer.close()

    operations = {step.operation for step in draft.transformations}
    assert operations <= {
        "drop_duplicate_rows",
        "trim_whitespace",
        "standardize_column_names",
    }
    assert not draft.questions
