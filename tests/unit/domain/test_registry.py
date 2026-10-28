"""Unit tests for registry domain entities."""

import pytest

from domain.entities.registry import Constraint, ConstraintKind, ModuleInput


def test_enum_constraint_requires_values() -> None:
    with pytest.raises(ValueError, match="enum constraints must declare values"):
        Constraint(ConstraintKind.ENUM)


def test_non_enum_constraint_rejects_values() -> None:
    with pytest.raises(ValueError, match="only enum constraints may declare values"):
        Constraint(ConstraintKind.NON_EMPTY, ("ignored",))


def test_constraint_values_must_not_be_blank() -> None:
    with pytest.raises(ValueError, match="constraint values must not be blank"):
        Constraint(ConstraintKind.ENUM, ("ok", " "))


def test_module_input_rejects_duplicate_constraint_kinds() -> None:
    with pytest.raises(ValueError, match="input constraints must be unique"):
        ModuleInput(
            name="value",
            type="string",
            required=True,
            constraints=(
                Constraint(ConstraintKind.NON_EMPTY),
                Constraint(ConstraintKind.NON_EMPTY),
            ),
        )
