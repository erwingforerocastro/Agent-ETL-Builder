"""Unit tests for the Ollama plan synthesizer."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from application.registry.specs import MODULE_SPECS
from domain.entities.run import PlanRequest
from domain.errors import PlanSynthesisError
from infrastructure.planning.ollama import OllamaPlanSynthesizer
from infrastructure.registry.bindings import MODULE_FUNCTIONS
from infrastructure.registry.module_registry import build_module_registry

SNAPSHOT = build_module_registry(MODULE_SPECS, MODULE_FUNCTIONS).snapshot()


def _request() -> PlanRequest:
    return PlanRequest(
        run_id="run-1",
        thread_id="thread-1",
        message="Remove duplicate rows",
        source="input.csv",
        destination="output.json",
    )


def _draft_content() -> str:
    return json.dumps(
        {
            "name": "clean_orders",
            "description": "Remove duplicate rows.",
            "transformations": [
                {"operation": "drop_duplicate_rows", "params": {}},
            ],
            "questions": [],
            "missing_inputs": [],
        }
    )


def _synthesizer(
    handler: Callable[[httpx.Request], httpx.Response],
) -> tuple[OllamaPlanSynthesizer, httpx.Client]:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return (
        OllamaPlanSynthesizer(
            model="llama3.1:8b",
            base_url="http://127.0.0.1:11434/",
            timeout_seconds=30,
            snapshot=SNAPSHOT,
            client=client,
        ),
        client,
    )


def test_synthesizer_sends_schema_and_parses_a_draft() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        payload = json.loads(request.content)
        assert payload["model"] == "llama3.1:8b"
        assert payload["stream"] is False
        assert payload["options"]["temperature"] == 0
        assert payload["format"]["additionalProperties"] is False
        assert payload["messages"][0]["role"] == "system"
        assert payload["messages"][-1] == {"role": "user", "content": "Remove duplicate rows"}
        return httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": _draft_content()}},
        )

    synthesizer, _ = _synthesizer(handler)

    draft = synthesizer.synthesize(_request())

    assert draft.name == "clean_orders"
    assert [step.operation for step in draft.transformations] == ["drop_duplicate_rows"]
    assert draft.transformations[0].step_id == "s1"


def test_timeout_is_reported_as_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        raise httpx.ReadTimeout("timeout")

    synthesizer, _ = _synthesizer(handler)

    with pytest.raises(PlanSynthesisError) as caught:
        synthesizer.synthesize(_request())

    assert caught.value.code == "PLAN_SYNTHESIS_TIMEOUT"
    assert caught.value.retryable is True


def test_http_error_is_reported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(503)

    synthesizer, _ = _synthesizer(handler)

    with pytest.raises(PlanSynthesisError) as caught:
        synthesizer.synthesize(_request())

    assert caught.value.code == "PLAN_SYNTHESIS_HTTP_ERROR"
    assert caught.value.retryable is True
    assert caught.value.context["status_code"] == 503


def test_invalid_json_is_reported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={"message": {"content": "not json"}},
        )

    synthesizer, _ = _synthesizer(handler)

    with pytest.raises(PlanSynthesisError) as caught:
        synthesizer.synthesize(_request())

    assert caught.value.code == "PLAN_SYNTHESIS_INVALID"


def test_missing_content_is_reported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"message": {}})

    synthesizer, _ = _synthesizer(handler)

    with pytest.raises(PlanSynthesisError) as caught:
        synthesizer.synthesize(_request())

    assert caught.value.code == "PLAN_SYNTHESIS_INVALID"


def test_oversized_response_is_reported_before_parsing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={"message": {"content": "x" * 70_000}},
        )

    synthesizer, _ = _synthesizer(handler)

    with pytest.raises(PlanSynthesisError) as caught:
        synthesizer.synthesize(_request())

    assert caught.value.code == "PLAN_SYNTHESIS_RESPONSE_TOO_LARGE"


def test_non_object_root_is_reported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"message": {"content": "[]"}})

    synthesizer, _ = _synthesizer(handler)

    with pytest.raises(PlanSynthesisError) as caught:
        synthesizer.synthesize(_request())

    assert caught.value.code == "PLAN_SYNTHESIS_INVALID"


def test_close_does_not_close_a_supplied_client() -> None:
    synthesizer, client = _synthesizer(
        lambda request: httpx.Response(
            200,
            json={"message": {"content": _draft_content()}},
        )
    )

    synthesizer.close()

    assert client.is_closed is False
    client.close()
