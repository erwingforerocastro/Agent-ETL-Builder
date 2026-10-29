"""Natural-language plan intake with deterministic I/O binding."""

from __future__ import annotations

from collections.abc import Sequence

from application.planning.binding import (
    SUPPORTED_DESTINATION_SUFFIXES,
    SUPPORTED_SOURCE_SUFFIXES,
    destination_operation_for_path,
    same_workspace_path,
    source_operation_for_path,
)
from application.planning.models import SourceSchema
from application.ports.plan_intake import PlanIntakeFactoryPort, PlanIntakePort
from application.ports.plan_parser import PlanParserPort
from application.ports.plan_synthesizer import ConversationTurn, PlanSynthesizerPort
from application.ports.source_schema import SourceSchemaPort
from domain.entities.plan import ExecutionPlan
from domain.entities.plan_draft import PlanDraft
from domain.entities.run import PlanIntakeResult, PlanRequest
from domain.errors import EtlError, PlanValidationError

_MAX_HISTORY_TURNS = 12


def _supported(values: Sequence[str]) -> str:
    return ", ".join(values)


class NaturalLanguagePlanIntake:
    """Turns a conversation into a validated, fully bound pipeline plan."""

    def __init__(
        self,
        *,
        synthesizer: PlanSynthesizerPort,
        parser: PlanParserPort,
        schema_probe: SourceSchemaPort | None = None,
    ) -> None:
        self._synthesizer = synthesizer
        self._parser = parser
        self._schema_probe = schema_probe
        self._history: list[ConversationTurn] = []
        self._source: str | None = None
        self._destination: str | None = None
        self._schema_source: str | None = None
        self._source_schema: SourceSchema | None = None

    def request(
        self,
        request: PlanRequest,
        *,
        attempt: int,
        previous_error: PlanValidationError | None = None,
    ) -> PlanIntakeResult:
        del attempt
        if request.mode != "pipeline":
            return self._clarify(
                (
                    "Assessment requests need an explicit source. Provide a source file "
                    "or submit a structured assessment plan.",
                ),
                ("source",),
            )

        if previous_error is None or not self._history or self._history[-1][0] != "user":
            self._append("user", request.message)

        if request.source is not None:
            self._source = request.source
        if request.destination is not None:
            self._destination = request.destination

        questions: list[str] = []
        missing_inputs: list[str] = []

        source_operation = source_operation_for_path(self._source)
        if self._source is None:
            questions.append(
                "Which workspace source file should I read? "
                f"Supported formats: {_supported(SUPPORTED_SOURCE_SUFFIXES)}."
            )
            missing_inputs.append("source")
        elif source_operation is None:
            questions.append(
                "The source format is not supported. "
                f"Use one of: {_supported(SUPPORTED_SOURCE_SUFFIXES)}."
            )
            missing_inputs.append("source")

        destination_operation = destination_operation_for_path(self._destination)
        if self._destination is None:
            questions.append(
                "Where should the output be written? "
                f"Supported formats: {_supported(SUPPORTED_DESTINATION_SUFFIXES)}."
            )
            missing_inputs.append("destination")
        elif destination_operation is None:
            questions.append(
                "The destination format is not supported. "
                f"Use one of: {_supported(SUPPORTED_DESTINATION_SUFFIXES)}."
            )
            missing_inputs.append("destination")

        if (
            source_operation is not None
            and destination_operation is not None
            and same_workspace_path(self._source, self._destination)
        ):
            questions.append("Destination must be a different workspace path from the source.")
            missing_inputs.append("destination")

        if questions:
            return self._clarify(tuple(questions), tuple(dict.fromkeys(missing_inputs)))

        source = self._source
        destination = self._destination
        if (
            source is None
            or destination is None
            or source_operation is None
            or destination_operation is None
        ):
            raise RuntimeError("plan binding is incomplete")

        source_schema = self._source_schema
        if self._schema_probe is not None and self._schema_source != source:
            try:
                source_schema = self._schema_probe.inspect(source)
            except EtlError as exc:
                return self._clarify(
                    (f"I could not inspect the source: {exc.message}.",),
                    ("source",),
                )
            self._source_schema = source_schema
            self._schema_source = source

        draft = self._synthesizer.synthesize(
            request,
            history=tuple(self._history),
            previous_error=previous_error,
            source_schema=source_schema,
        )
        if draft.needs_input:
            return self._clarify(draft.questions, draft.missing_inputs)

        plan = self._parser.parse(
            self._plan_payload(
                request,
                draft,
                source,
                destination,
                source_operation,
                destination_operation,
            )
        )
        return PlanIntakeResult(plan=plan)

    def _plan_payload(
        self,
        request: PlanRequest,
        draft: PlanDraft,
        source: str,
        destination: str,
        source_operation: str,
        destination_operation: str,
    ) -> dict[str, object]:
        return {
            "plan_version": "1.0",
            "mode": "pipeline",
            "run_id": request.run_id,
            "name": draft.name,
            "description": draft.description,
            "source": {
                "operation": source_operation,
                "params": {"path": source},
            },
            "transformations": [
                {
                    "step_id": transformation.step_id,
                    "operation": transformation.operation,
                    "params": dict(transformation.params),
                }
                for transformation in draft.transformations
            ],
            "destination": {
                "operation": destination_operation,
                "params": {"path": destination},
            },
            "chunking": {"enabled": False, "size": 10_000},
            "on_error": "fail_fast",
            "approval_required": True,
        }

    def _clarify(
        self,
        questions: Sequence[str],
        missing_inputs: Sequence[str],
    ) -> PlanIntakeResult:
        cleaned_questions = tuple(question.strip() for question in questions if question.strip())
        cleaned_missing = tuple(item.strip() for item in missing_inputs if item.strip())
        if not cleaned_questions:
            cleaned_questions = ("I need more information before I can build the plan.",)
        if not cleaned_missing:
            cleaned_missing = ("context",)
        self._append("assistant", "\n".join(cleaned_questions))
        return PlanIntakeResult(
            questions=cleaned_questions,
            missing_inputs=cleaned_missing,
        )

    def _append(self, role: str, content: str) -> None:
        text = content.strip()
        if not text:
            return
        if self._history and self._history[-1] == (role, text):
            return
        self._history.append((role, text))
        if len(self._history) > _MAX_HISTORY_TURNS:
            del self._history[: len(self._history) - _MAX_HISTORY_TURNS]


class NaturalLanguagePlanIntakeFactory(PlanIntakeFactoryPort):
    """Creates one stateful natural-language intake per run."""

    def __init__(
        self,
        *,
        synthesizer: PlanSynthesizerPort,
        parser: PlanParserPort,
        schema_probe: SourceSchemaPort | None = None,
    ) -> None:
        self._synthesizer = synthesizer
        self._parser = parser
        self._schema_probe = schema_probe

    def create(self, plan: ExecutionPlan | None) -> PlanIntakePort:
        del plan
        return NaturalLanguagePlanIntake(
            synthesizer=self._synthesizer,
            parser=self._parser,
            schema_probe=self._schema_probe,
        )


__all__ = ["NaturalLanguagePlanIntake", "NaturalLanguagePlanIntakeFactory"]
