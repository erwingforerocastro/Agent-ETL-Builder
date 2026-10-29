"""Ollama-backed natural-language plan synthesis."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from application.planning.models import SourceSchema
from application.planning.prompt import PlanPromptBuilder
from application.planning.schema import build_plan_draft_schema
from application.ports.plan_synthesizer import ConversationTurn
from domain.entities.plan_draft import PlanDraft
from domain.entities.registry import RegistrySnapshot
from domain.entities.run import PlanRequest
from domain.errors import PlanSynthesisError, PlanValidationError
from infrastructure.planning.draft_schema import parse_plan_draft

_MAX_RESPONSE_BYTES = 65_536
_MAX_TOKENS = 2_048


def _error(
    code: str,
    message: str,
    *,
    retryable: bool = False,
    context: Mapping[str, object] | None = None,
) -> PlanSynthesisError:
    return PlanSynthesisError(
        code=code,
        message=message,
        module=__name__,
        retryable=retryable,
        context=context,
    )


class OllamaPlanSynthesizer:
    """Generates a strict transformation draft through a local Ollama server."""

    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        timeout_seconds: float,
        snapshot: RegistrySnapshot,
        client: httpx.Client | None = None,
    ) -> None:
        if not model.strip():
            raise ValueError("model must not be blank")
        if not base_url.strip():
            raise ValueError("base_url must not be blank")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        self._model = model.strip()
        self._base_url = base_url.rstrip("/")
        self._schema = build_plan_draft_schema(snapshot)
        self._prompt = PlanPromptBuilder(snapshot)
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(timeout_seconds),
        )
        self._owns_client = client is None

    def synthesize(
        self,
        request: PlanRequest,
        *,
        history: Sequence[ConversationTurn] = (),
        previous_error: PlanValidationError | None = None,
        source_schema: SourceSchema | None = None,
    ) -> PlanDraft:
        """Ask the model for a draft and parse it strictly."""
        messages = self._prompt.messages(
            request,
            history=history,
            previous_error=previous_error,
            source=request.source,
            destination=request.destination,
            source_schema=source_schema,
        )
        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "format": self._schema,
            "options": {
                "temperature": 0,
                "num_predict": _MAX_TOKENS,
            },
        }
        try:
            response = self._client.post(f"{self._base_url}/api/chat", json=payload)
        except httpx.TimeoutException as exc:
            raise _error(
                "PLAN_SYNTHESIS_TIMEOUT",
                "The plan builder timed out",
                retryable=True,
                context={"model": self._model},
            ) from exc
        except httpx.RequestError as exc:
            raise _error(
                "PLAN_SYNTHESIS_UNAVAILABLE",
                "The plan builder is unavailable",
                retryable=True,
                context={"model": self._model, "error_type": type(exc).__name__},
            ) from exc

        if response.status_code >= 400:
            raise _error(
                "PLAN_SYNTHESIS_HTTP_ERROR",
                "The plan builder returned an error",
                retryable=response.status_code >= 500 or response.status_code == 429,
                context={"model": self._model, "status_code": response.status_code},
            )

        content = self._content(response)
        if len(content.encode("utf-8")) > _MAX_RESPONSE_BYTES:
            raise _error(
                "PLAN_SYNTHESIS_RESPONSE_TOO_LARGE",
                "The plan builder response is too large",
                context={"model": self._model, "max_bytes": _MAX_RESPONSE_BYTES},
            )
        try:
            raw = json.loads(content)
        except json.JSONDecodeError as exc:
            raise _error(
                "PLAN_SYNTHESIS_INVALID",
                "The plan builder returned invalid JSON",
                context={"model": self._model, "reason": exc.msg},
            ) from exc
        if not isinstance(raw, Mapping):
            raise _error(
                "PLAN_SYNTHESIS_INVALID",
                "The plan builder returned an invalid draft",
                context={"model": self._model, "reason": "root is not an object"},
            )
        return parse_plan_draft(raw)

    def _content(self, response: httpx.Response) -> str:
        try:
            data: Any = response.json()
        except ValueError as exc:
            raise _error(
                "PLAN_SYNTHESIS_INVALID",
                "The plan builder returned invalid JSON",
                context={"model": self._model, "reason": "response is not JSON"},
            ) from exc
        message = data.get("message") if isinstance(data, Mapping) else None
        content = message.get("content") if isinstance(message, Mapping) else None
        if not isinstance(content, str) or not content.strip():
            raise _error(
                "PLAN_SYNTHESIS_INVALID",
                "The plan builder returned no content",
                context={"model": self._model},
            )
        return content

    def close(self) -> None:
        """Close the owned HTTP client."""
        if self._owns_client:
            self._client.close()


__all__ = ["OllamaPlanSynthesizer"]
