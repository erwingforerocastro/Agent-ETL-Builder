"""Concrete allowlisted callables for application registry specs."""

from collections.abc import Callable, Mapping

import pandas as pd

from infrastructure.ingestion.csv import read_csv
from infrastructure.ingestion.json import read_json, read_jsonl
from infrastructure.ingestion.parquet import read_parquet
from infrastructure.loaders.csv import save_csv
from infrastructure.transformations.cast_column import cast_column
from infrastructure.transformations.change_text_case import change_text_case
from infrastructure.transformations.drop_duplicates import drop_duplicate_rows
from infrastructure.transformations.drop_empty_rows import drop_empty_rows
from infrastructure.transformations.fill_missing_values import fill_missing_values
from infrastructure.transformations.filter_rows import filter_rows
from infrastructure.transformations.normalize_dates import normalize_dates
from infrastructure.transformations.replace_values import replace_values
from infrastructure.transformations.standardize_column_names import (
    standardize_column_names,
)
from infrastructure.transformations.trim_whitespace import trim_whitespace

ALLOWED_MODULE_PREFIX = "infrastructure."
CAPABILITY_PACKAGES: Mapping[str, str] = {"dataframe": "pandas"}

MODULE_FUNCTIONS: Mapping[str, Callable[..., pd.DataFrame]] = {
    "drop_duplicate_rows": drop_duplicate_rows,
    "drop_empty_rows": drop_empty_rows,
    "trim_whitespace": trim_whitespace,
    "standardize_column_names": standardize_column_names,
    "cast_column": cast_column,
    "filter_rows": filter_rows,
    "fill_missing_values": fill_missing_values,
    "normalize_dates": normalize_dates,
    "change_text_case": change_text_case,
    "replace_values": replace_values,
    "read_csv": read_csv,
    "read_json": read_json,
    "read_jsonl": read_jsonl,
    "read_parquet": read_parquet,
    "save_csv": save_csv,
}


__all__ = ["ALLOWED_MODULE_PREFIX", "CAPABILITY_PACKAGES", "MODULE_FUNCTIONS"]
