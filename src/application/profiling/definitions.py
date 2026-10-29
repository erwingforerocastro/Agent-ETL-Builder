"""Explicit metric definitions shared by profiling and artifact writers."""

from __future__ import annotations

from typing import Final

COLUMN_COMPLETENESS_FORMULA: Final[str] = "non_null_non_empty_values / total_rows"
ROW_COMPLETENESS_FORMULA: Final[str] = "rows_without_null_or_empty_cells / total_rows"
DATASET_COMPLETENESS_FORMULA: Final[str] = "non_null_non_empty_cells / total_cells"
DUPLICATE_ROWS_FORMULA: Final[str] = "distinct_row_fingerprints / total_rows"
COLUMN_UNIQUENESS_FORMULA: Final[str] = (
    "distinct_non_null_non_empty_values / non_null_non_empty_values"
)
ACCURACY_FORMULA: Final[str] = "N/A (formula not provided)"
NO_RULES_FORMULA: Final[str] = "N/A (no rules declared)"
DEFAULT_QUALITY_THRESHOLD: Final[float] = 1.0


__all__ = [
    "ACCURACY_FORMULA",
    "COLUMN_COMPLETENESS_FORMULA",
    "COLUMN_UNIQUENESS_FORMULA",
    "DATASET_COMPLETENESS_FORMULA",
    "DEFAULT_QUALITY_THRESHOLD",
    "DUPLICATE_ROWS_FORMULA",
    "NO_RULES_FORMULA",
    "ROW_COMPLETENESS_FORMULA",
]
