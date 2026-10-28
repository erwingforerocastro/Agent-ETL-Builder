"""Concrete allowlisted callables for application registry specs."""

from collections.abc import Callable, Mapping

import pandas as pd

from infrastructure.ingestion.csv import read_csv
from infrastructure.loaders.csv import save_csv
from infrastructure.transformations.cast_column import cast_column
from infrastructure.transformations.drop_duplicates import drop_duplicate_rows
from infrastructure.transformations.drop_empty_rows import drop_empty_rows
from infrastructure.transformations.standardize_column_names import (
    standardize_column_names,
)
from infrastructure.transformations.trim_whitespace import trim_whitespace

MODULE_FUNCTIONS: Mapping[str, Callable[..., pd.DataFrame]] = {
    "drop_duplicate_rows": drop_duplicate_rows,
    "drop_empty_rows": drop_empty_rows,
    "trim_whitespace": trim_whitespace,
    "standardize_column_names": standardize_column_names,
    "cast_column": cast_column,
    "read_csv": read_csv,
    "save_csv": save_csv,
}


__all__ = ["MODULE_FUNCTIONS"]
