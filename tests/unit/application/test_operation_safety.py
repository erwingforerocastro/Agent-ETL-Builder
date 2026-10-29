"""Unit tests for destructive-operation classification."""

import pytest

from application.validation.operations import OperationSafetyPolicy


@pytest.mark.parametrize(
    ("operation", "params", "expected"),
    [
        ("drop_duplicate_rows", {}, True),
        ("drop_empty_rows", {}, True),
        ("filter_rows", {}, True),
        ("cast_column", {"errors": "coerce"}, True),
        ("cast_column", {"errors": "raise"}, False),
        ("cast_column", {}, False),
        ("normalize_dates", {"errors": "coerce"}, True),
        ("normalize_dates", {"errors": "raise"}, False),
        ("normalize_dates", {}, False),
        ("replace_values", {"new": None}, True),
        ("replace_values", {"new": None, "old": "N/A"}, True),
        ("replace_values", {"new": "unknown", "old": "N/A"}, False),
        ("replace_values", {"old": "N/A"}, True),
        ("fill_missing_values", {}, False),
        ("trim_whitespace", {}, False),
        ("change_text_case", {}, False),
        ("standardize_column_names", {}, False),
        ("save_csv", {}, False),
    ],
)
def test_is_destructive(operation: str, params: dict[str, object], expected: bool) -> None:
    assert OperationSafetyPolicy.is_destructive(operation, params) is expected
