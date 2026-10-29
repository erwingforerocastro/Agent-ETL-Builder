"""Draft transformation plan before source and destination binding."""

from __future__ import annotations

from dataclasses import dataclass

from domain.entities._validation import require_text
from domain.entities.plan import PlanTransformation


@dataclass(frozen=True, slots=True)
class PlanDraft:
    """A natural-language plan candidate without I/O binding metadata."""

    name: str
    description: str
    transformations: tuple[PlanTransformation, ...] = ()
    questions: tuple[str, ...] = ()
    missing_inputs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_text(self.name, "name")
        require_text(self.description, "description")
        transformations = tuple(self.transformations)
        questions = tuple(self.questions)
        missing_inputs = tuple(self.missing_inputs)
        object.__setattr__(self, "transformations", transformations)
        object.__setattr__(self, "questions", questions)
        object.__setattr__(self, "missing_inputs", missing_inputs)
        if any(not question.strip() for question in questions):
            raise ValueError("questions must not be blank")
        if any(not item.strip() for item in missing_inputs):
            raise ValueError("missing_inputs must not be blank")
        step_ids = [transformation.step_id for transformation in transformations]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("transformation step_id values must be unique")

    @property
    def needs_input(self) -> bool:
        """Return whether the draft asks the user for missing information."""
        return bool(self.questions or self.missing_inputs)


__all__ = ["PlanDraft"]
