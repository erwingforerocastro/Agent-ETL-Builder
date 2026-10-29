"""Explicit metric definitions shared by profiling and artifact writers."""

from __future__ import annotations

from typing import Final

from domain.entities.profiling import QualityRule, RuleKind

COLUMN_COMPLETENESS_FORMULA: Final[str] = "non_null_non_empty_values / total_rows"
ROW_COMPLETENESS_FORMULA: Final[str] = "rows_without_null_or_empty_cells / total_rows"
DATASET_COMPLETENESS_FORMULA: Final[str] = "non_null_non_empty_cells / total_cells"
DUPLICATE_ROWS_FORMULA: Final[str] = "distinct_row_fingerprints / total_rows"
COLUMN_UNIQUENESS_FORMULA: Final[str] = (
    "distinct_non_null_non_empty_values / non_null_non_empty_values"
)
ACCURACY_FORMULA: Final[str] = "N/A (formula not provided)"
NO_RULES_FORMULA: Final[str] = "N/A (no rules declared)"

_RULE_FORMULAS: Final[dict[RuleKind, str]] = {
    RuleKind.REQUIRED: "non_null_non_empty_values / total_rows",
    RuleKind.UNIQUE_KEY: ("distinct_complete_key_tuples / rows_with_all_key_values_present"),
    RuleKind.REGEX: "present_values_full_matching_pattern / present_values",
    RuleKind.RANGE: "present_values_parseable_and_within_range / present_values",
    RuleKind.DOMAIN: "present_values_in_allowed_domain / present_values",
    RuleKind.TYPE: "present_values_parseable_as_declared_type / present_values",
    RuleKind.COMPARE: "rows_where_comparison_holds / rows_with_both_values_present",
}


def rule_metric_name(rule: QualityRule) -> str:
    """Return a stable metric name for a declared rule."""
    return f"{rule.family.value}.{rule.kind.value}"


def rule_formula(rule: QualityRule) -> str:
    """Return the explicit formula text for a declared rule."""
    return _RULE_FORMULAS[rule.kind]


__all__ = [
    "ACCURACY_FORMULA",
    "COLUMN_COMPLETENESS_FORMULA",
    "COLUMN_UNIQUENESS_FORMULA",
    "DATASET_COMPLETENESS_FORMULA",
    "DUPLICATE_ROWS_FORMULA",
    "NO_RULES_FORMULA",
    "ROW_COMPLETENESS_FORMULA",
    "rule_formula",
    "rule_metric_name",
]
