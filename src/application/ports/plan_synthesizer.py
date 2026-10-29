"""Natural-language plan synthesis contract."""

from collections.abc import Sequence
from typing import Protocol

from application.planning.models import SourceSchema
from domain.entities.plan_draft import PlanDraft
from domain.entities.run import PlanRequest
from domain.errors import PlanValidationError

ConversationTurn = tuple[str, str]


class PlanSynthesizerPort(Protocol):
    """Turns a conversation into a transformation draft."""

    def synthesize(
        self,
        request: PlanRequest,
        *,
        history: Sequence[ConversationTurn] = (),
        previous_error: PlanValidationError | None = None,
        source_schema: SourceSchema | None = None,
    ) -> PlanDraft: ...


__all__ = ["ConversationTurn", "PlanSynthesizerPort"]
