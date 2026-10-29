"""Prompt construction for natural-language plan synthesis."""

from __future__ import annotations

import json
from collections.abc import Sequence

from application.planning.models import SourceSchema
from application.ports.plan_synthesizer import ConversationTurn
from domain.entities.registry import ModuleMetadata, RegistrySnapshot
from domain.entities.run import PlanRequest
from domain.errors import PlanValidationError

_MAX_ERROR_CONTEXT = 2_000


def _format_input(item_name: str, declared: str, required: bool, default: str | None) -> str:
    parts = [f"{item_name}: {declared}"]
    parts.append("required" if required else "optional")
    if default is not None:
        parts.append(f"default={default!r}")
    return ", ".join(parts)


def _format_module(module: ModuleMetadata) -> str:
    inputs = [
        _format_input(item.name, item.type, item.required, item.default)
        for item in module.inputs
        if not item.pipeline_input
    ]
    example = module.examples[0] if module.examples else {}
    return (
        f"- {module.name}({'; '.join(inputs) or 'no parameters'}): {module.description} "
        f"Example params: {json.dumps(example, ensure_ascii=False, sort_keys=True)}"
    )


def _format_schema(schema: SourceSchema | None) -> str:
    if schema is None:
        return ""
    if not schema.columns:
        return (
            "\nSource columns (authoritative): none were detected. "
            "Only column-agnostic transformations are allowed.\n"
        )
    columns = ", ".join(schema.columns)
    text = f"\nSource columns (authoritative): {columns}\n"
    if schema.dtypes:
        text += f"Source dtypes: {', '.join(schema.dtypes)}\n"
    return text + "Only use these column names. Never invent a column.\n"


def _format_error(error: PlanValidationError | None) -> str:
    if error is None:
        return ""
    context = json.dumps(
        dict(error.context),
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return (
        "\n\nThe previous draft was rejected by validation.\n"
        f"Code: {error.code}\n"
        f"Message: {error.message}\n"
        f"Details: {context[:_MAX_ERROR_CONTEXT]}\n"
        "Return a corrected draft that satisfies the rules."
    )


class PlanPromptBuilder:
    """Builds deterministic chat messages for the transformation draft schema."""

    def __init__(self, snapshot: RegistrySnapshot) -> None:
        self._snapshot = snapshot

    def system_prompt(
        self,
        *,
        source: str,
        destination: str,
        source_schema: SourceSchema | None = None,
        previous_error: PlanValidationError | None = None,
    ) -> str:
        catalog = "\n".join(
            _format_module(module)
            for module in self._snapshot.modules
            if any(item.pipeline_input for item in module.inputs) and not module.side_effects
        )
        schema_text = _format_schema(source_schema)
        return (
            "You are a conservative ETL plan builder. Build the smallest valid "
            "transformation plan for the user's request.\n\n"
            "Rules:\n"
            "- Use only the operations listed below.\n"
            "- Use only the parameters shown for each operation. Never add extra parameters.\n"
            "- Do not include source or destination operations; the system binds them.\n"
            "- Do not include step IDs; the system assigns them.\n"
            "- The source and destination paths are already supplied and fixed. Never ask "
            "for them and never repeat them in the output.\n"
            "- Do not invent column names. If a required column is not named in the request, "
            "ask for it in questions and list it in missing_inputs.\n"
            "- If the request can be satisfied with the allowed operations, return empty "
            "questions and missing_inputs.\n"
            "- If the request is already satisfied without transformations, return an empty "
            "transformations list.\n"
            "- Include only transformations the user explicitly requested or that are "
            "strictly necessary. Prefer the smallest plan, usually zero to three steps.\n"
            "- Never add filter_rows, drop_empty_rows, fill_missing_values, normalize_dates, "
            "cast_column, or change_text_case unless the user explicitly asks for that "
            "behavior.\n"
            "- For a general request to clean data, limit the plan to removing exact "
            "duplicate rows and trimming whitespace. Do not filter or drop rows by value.\n"
            "- Only use normalize_dates on a column whose source dtype is a date or datetime.\n"
            "- Prefer non-destructive operations unless the user explicitly requests a "
            "destructive change.\n"
            "- Use a short snake_case pipeline name that describes the outcome, not an "
            "operation name.\n"
            "- Return only JSON matching the supplied schema. Do not use markdown fences.\n\n"
            f"Registry version: {self._snapshot.version}\n"
            f"Source path (fixed): {source}\n"
            f"Destination path (fixed): {destination}\n"
            f"{schema_text}"
            f"{_format_error(previous_error)}\n\n"
            f"Allowed transformation operations:\n{catalog}"
        )

    def messages(
        self,
        request: PlanRequest,
        *,
        history: Sequence[ConversationTurn] = (),
        previous_error: PlanValidationError | None = None,
        source: str | None = None,
        destination: str | None = None,
        source_schema: SourceSchema | None = None,
    ) -> list[dict[str, str]]:
        """Return the system prompt followed by the bounded conversation history."""
        resolved_source = source or request.source or ""
        resolved_destination = destination or request.destination or ""
        messages = [
            {
                "role": "system",
                "content": self.system_prompt(
                    source=resolved_source,
                    destination=resolved_destination,
                    source_schema=source_schema,
                    previous_error=previous_error,
                ),
            }
        ]
        messages.extend(
            {"role": role, "content": content}
            for role, content in history
            if role in {"user", "assistant"} and content.strip()
        )
        if not any(message["role"] == "user" for message in messages[1:]):
            messages.append({"role": "user", "content": request.message})
        return messages


__all__ = ["PlanPromptBuilder"]
