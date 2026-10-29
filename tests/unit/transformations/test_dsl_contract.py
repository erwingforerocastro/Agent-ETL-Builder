"""Registry-wide determinism and idempotence contract for transformations."""

from collections.abc import Callable, Mapping

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from application.registry.specs import MODULE_SPECS
from domain.entities.registry import ModuleMetadata
from infrastructure.registry.bindings import MODULE_FUNCTIONS
from infrastructure.registry.module_registry import build_module_registry

FrameFactory = Callable[[], pd.DataFrame]


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id": [1, 2, 2, 4],
            "name": [" Ada ", "BOB", None, "Cy"],
            "amount": [1.0, None, 3.0, 4.0],
            "created_at": ["2026-01-02", "2026-12-31", None, "bad"],
            "status": ["N/A", "active", "N/A", "active"],
        }
    )


def _standardize_frame() -> pd.DataFrame:
    return pd.DataFrame({" First Name ": [" Ada "], "ID": [1]})


_CASES: Mapping[str, tuple[Mapping[str, object], FrameFactory]] = {
    "drop_duplicate_rows": ({"subset": ["id"]}, _frame),
    "drop_empty_rows": ({"subset": ["name"]}, _frame),
    "trim_whitespace": ({"columns": ["name"]}, _frame),
    "standardize_column_names": ({"case": "lower"}, _standardize_frame),
    "cast_column": (
        {"column": "amount", "target_type": "float", "errors": "coerce"},
        _frame,
    ),
    "filter_rows": ({"column": "status", "operator": "not_equals", "value": "N/A"}, _frame),
    "fill_missing_values": ({"column": "amount", "method": "mean"}, _frame),
    "normalize_dates": (
        {"column": "created_at", "output_format": "%Y-%m-%d", "errors": "coerce"},
        _frame,
    ),
    "change_text_case": ({"columns": ["name"], "case": "lower"}, _frame),
    "replace_values": ({"columns": ["status"], "old": "N/A", "new": None}, _frame),
}


def _transformation_metadata() -> dict[str, ModuleMetadata]:
    registry = build_module_registry(MODULE_SPECS, MODULE_FUNCTIONS)
    return {
        module.name: module
        for module in registry.snapshot().modules
        if any(item.pipeline_input and item.required for item in module.inputs)
        and not module.side_effects
    }


@pytest.mark.parametrize("operation", sorted(_CASES))
def test_every_transformation_is_deterministic_and_idempotent(operation: str) -> None:
    metadata = _transformation_metadata()[operation]
    params, frame_factory = _CASES[operation]
    df = frame_factory()
    original = df.copy(deep=True)
    function = MODULE_FUNCTIONS[operation]

    once = function(df, **params)
    twice = function(once, **params)

    assert metadata.idempotent
    assert not metadata.side_effects
    assert any(item.pipeline_input and item.required for item in metadata.inputs)
    assert_frame_equal(once, twice)
    assert_frame_equal(df, original)


def test_every_registered_transformation_has_a_contract_case() -> None:
    assert set(_CASES) == set(_transformation_metadata())


_SEQUENCE = (
    ("drop_duplicate_rows", {"subset": ["id"]}),
    ("drop_empty_rows", {"subset": ["name"]}),
    ("trim_whitespace", {"columns": ["name"]}),
    ("change_text_case", {"columns": ["name"], "case": "upper"}),
    ("cast_column", {"column": "amount", "target_type": "float", "errors": "coerce"}),
    ("fill_missing_values", {"column": "amount", "method": "mean"}),
    (
        "normalize_dates",
        {"column": "created_at", "output_format": "%Y-%m-%d", "errors": "coerce"},
    ),
    ("replace_values", {"columns": ["status"], "old": "N/A", "new": None}),
    ("filter_rows", {"column": "created_at", "operator": "is_not_null"}),
    ("standardize_column_names", {"case": "lower"}),
)


def _apply_sequence(df: pd.DataFrame) -> pd.DataFrame:
    data = df
    for operation, params in _SEQUENCE:
        data = MODULE_FUNCTIONS[operation](data, **params)
    return data


def test_transformation_sequence_is_idempotent_and_copy_on_write() -> None:
    df = _frame()
    original = df.copy(deep=True)

    once = _apply_sequence(df)
    twice = _apply_sequence(once)

    assert_frame_equal(once, twice)
    assert_frame_equal(df, original)
