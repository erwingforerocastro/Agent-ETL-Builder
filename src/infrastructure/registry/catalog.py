"""Static allowlist and signature-derived metadata for approved modules."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

import pandas as pd

from domain.entities.registry import RegistrySnapshot
from infrastructure.registry.constants import (
    ALLOWED_MODULE_PREFIX,
    OUTPUT_DESCRIPTION,
    REGISTRY_VERSION,
)
from infrastructure.ingestion.csv import read_csv
from infrastructure.loaders.csv import save_csv
from infrastructure.transformations.cast_column import cast_column
from infrastructure.transformations.drop_duplicates import drop_duplicate_rows
from infrastructure.transformations.drop_empty_rows import drop_empty_rows
from infrastructure.transformations.standardize_column_names import (
    standardize_column_names,
)
from infrastructure.transformations.trim_whitespace import trim_whitespace

# Re-export for backward compatibility
__all__ = [
    "REGISTRY_VERSION",
    "ALLOWED_MODULE_PREFIX",
    "OUTPUT_DESCRIPTION",
    "ModuleSpec",
    "MODULE_SPECS",
]


@dataclass(frozen=True, slots=True)
class ModuleSpec:
    name: str
    version: str
    function: Callable[..., pd.DataFrame]
    description: str
    constraints: Mapping[str, tuple[str, ...]]
    examples: tuple[Mapping[str, object], ...]
    supports_chunking: bool
    idempotent: bool
    security_notes: str
    dependencies: tuple[str, ...] = ("pandas",)
    side_effects: tuple[str, ...] = ()
    supported_dialects: tuple[str, ...] = ()


MODULE_SPECS: tuple[ModuleSpec, ...] = (
    ModuleSpec(
        name="drop_duplicate_rows",
        version="1.0.0",
        function=drop_duplicate_rows,
        description="Drop duplicate rows by all columns or a selected subset.",
        constraints={
            "subset": ("non-empty when provided", "column names must exist"),
            "keep": ("enum: first or last",),
        },
        examples=({"subset": ["customer_id"], "keep": "last"},),
        supports_chunking=False,
        idempotent=True,
        security_notes="DataFrame-only; no I/O or code execution.",
    ),
    ModuleSpec(
        name="drop_empty_rows",
        version="1.0.0",
        function=drop_empty_rows,
        description="Drop rows whose selected values are all null or blank text.",
        constraints={"subset": ("non-empty when provided", "column names must exist")},
        examples=({"subset": ["email"]},),
        supports_chunking=True,
        idempotent=True,
        security_notes="DataFrame-only; no I/O or code execution.",
    ),
    ModuleSpec(
        name="trim_whitespace",
        version="1.0.0",
        function=trim_whitespace,
        description="Trim leading, trailing, or both whitespace styles in text columns.",
        constraints={
            "columns": ("non-empty when provided", "text columns only"),
            "policy": ("enum: both, leading, or trailing",),
        },
        examples=({"columns": ["name"], "policy": "both"},),
        supports_chunking=True,
        idempotent=True,
        security_notes="DataFrame-only; no I/O or code execution.",
    ),
    ModuleSpec(
        name="standardize_column_names",
        version="1.0.0",
        function=standardize_column_names,
        description="Normalize column names to collision-free snake_case.",
        constraints={"case": ("enum: lower, upper, or preserve",)},
        examples=({"case": "upper"},),
        supports_chunking=True,
        idempotent=True,
        security_notes="DataFrame-only; no I/O or code execution.",
    ),
    ModuleSpec(
        name="cast_column",
        version="1.0.0",
        function=cast_column,
        description="Cast one column to string, integer, or float.",
        constraints={
            "column": ("column name must exist",),
            "target_type": ("enum: string, integer, or float",),
            "errors": ("enum: raise or coerce",),
        },
        examples=({"column": "amount", "target_type": "float", "errors": "coerce"},),
        supports_chunking=True,
        idempotent=True,
        security_notes="DataFrame-only; no I/O or code execution.",
    ),
    ModuleSpec(
        name="read_csv",
        version="1.0.0",
        function=read_csv,
        description="Read a CSV file into a DataFrame",
        constraints={"path": ("workspace-relative path",)},
        examples=({"path": "input.csv"},),
        supports_chunking=True,
        idempotent=True,
        security_notes="Path is confined to the workspace.",
    ),
    ModuleSpec(
        name="save_csv",
        version="1.0.0",
        function=save_csv,
        description="Save a DataFrame to a CSV file",
        constraints={"path": ("workspace-relative path",)},
        examples=({"path": "output.csv"},),
        supports_chunking=False,
        idempotent=False,
        security_notes="Writes a file.",
        side_effects=("writes a file",),
    ),
)


# All validation logic moved to validators.py
# All helper functions moved to functions.py
# Constants moved to constants.py
from infrastructure.registry.functions import build_snapshot
from infrastructure.registry.validators import (
    DependencyValidator,
    ExampleValidator,
    ModuleMetadataBuilder,
    RegistrySnapshotBuilder,
    RegistryValidator,
    SignatureValidator,
    TypeValidator,
    _annotation_to_text,
    _format_default,
    _metadata_for,
    _registry_error,
    _validate_default,
    _validate_dependencies,
    _validate_example_value,
    _validate_examples,
    _value_matches_type,
)

__all__ = [
    "ALLOWED_MODULE_PREFIX",
    "DependencyValidator",
    "ExampleValidator",
    "MODULE_SPECS",
    "ModuleMetadataBuilder",
    "ModuleSpec",
    "OUTPUT_DESCRIPTION",
    "REGISTRY_VERSION",
    "RegistrySnapshotBuilder",
    "RegistryValidator",
    "SignatureValidator",
    "TypeValidator",
    "build_snapshot",
    "_annotation_to_text",
    "_format_default",
    "_metadata_for",
    "_registry_error",
    "_validate_default",
    "_validate_dependencies",
    "_validate_example_value",
    "_validate_examples",
    "_value_matches_type",
]

