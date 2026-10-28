"""Static allowlist and metadata policy for approved modules."""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModuleSpec:
    """Application-level contract for one allowlisted module."""

    name: str
    version: str
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
        description="Save a DataFrame to a CSV file",
        constraints={"path": ("workspace-relative path",)},
        examples=({"path": "output.csv"},),
        supports_chunking=False,
        idempotent=False,
        security_notes="Writes a file.",
        side_effects=("writes a file",),
    ),
)


__all__ = ["MODULE_SPECS", "ModuleSpec"]
