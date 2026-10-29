"""Static allowlist and metadata policy for approved modules."""

from collections.abc import Mapping
from dataclasses import dataclass

from application.registry.vocabulary import (
    CAST_ERROR_MODES,
    CAST_TARGET_TYPES,
    COLUMN_CASES,
    KEEP_POLICIES,
    WHITESPACE_POLICIES,
)
from domain.entities.registry import Constraint, ConstraintKind


@dataclass(frozen=True, slots=True)
class ModuleSpec:
    """Application-level contract for one allowlisted module."""

    name: str
    version: str
    description: str
    constraints: Mapping[str, tuple[Constraint, ...]]
    examples: tuple[Mapping[str, object], ...]
    supports_chunking: bool
    idempotent: bool
    security_notes: str
    dependencies: tuple[str, ...] = ("dataframe",)
    side_effects: tuple[str, ...] = ()
    supported_dialects: tuple[str, ...] = ()


MODULE_SPECS: tuple[ModuleSpec, ...] = (
    ModuleSpec(
        name="drop_duplicate_rows",
        version="1.0.0",
        description="Drop duplicate rows by all columns or a selected subset.",
        constraints={
            "subset": (
                Constraint(ConstraintKind.NON_EMPTY),
                Constraint(ConstraintKind.COLUMN_EXISTS),
            ),
            "keep": (Constraint(ConstraintKind.ENUM, KEEP_POLICIES),),
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
        constraints={
            "subset": (
                Constraint(ConstraintKind.NON_EMPTY),
                Constraint(ConstraintKind.COLUMN_EXISTS),
            )
        },
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
            "columns": (
                Constraint(ConstraintKind.NON_EMPTY),
                Constraint(ConstraintKind.TEXT_COLUMNS),
            ),
            "policy": (Constraint(ConstraintKind.ENUM, WHITESPACE_POLICIES),),
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
        constraints={"case": (Constraint(ConstraintKind.ENUM, COLUMN_CASES),)},
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
            "column": (Constraint(ConstraintKind.COLUMN_NAME),),
            "target_type": (Constraint(ConstraintKind.ENUM, CAST_TARGET_TYPES),),
            "errors": (Constraint(ConstraintKind.ENUM, CAST_ERROR_MODES),),
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
        constraints={"path": (Constraint(ConstraintKind.PATH),)},
        examples=({"path": "input.csv"},),
        supports_chunking=True,
        idempotent=True,
        security_notes="Read-only; path is confined to the workspace.",
        supported_dialects=("csv",),
    ),
    ModuleSpec(
        name="read_json",
        version="1.0.0",
        description="Read a JSON array file into a DataFrame",
        constraints={"path": (Constraint(ConstraintKind.PATH),)},
        examples=({"path": "input.json"},),
        supports_chunking=True,
        idempotent=True,
        security_notes="Read-only; path is confined to the workspace.",
        supported_dialects=("json",),
    ),
    ModuleSpec(
        name="read_jsonl",
        version="1.0.0",
        description="Read a JSON Lines file into a DataFrame",
        constraints={"path": (Constraint(ConstraintKind.PATH),)},
        examples=({"path": "input.jsonl"},),
        supports_chunking=True,
        idempotent=True,
        security_notes="Read-only; path is confined to the workspace.",
        supported_dialects=("jsonl",),
    ),
    ModuleSpec(
        name="read_parquet",
        version="1.0.0",
        description="Read a Parquet file into a DataFrame",
        constraints={
            "path": (Constraint(ConstraintKind.PATH),),
            "columns": (Constraint(ConstraintKind.NON_EMPTY),),
        },
        examples=({"path": "input.parquet"},),
        supports_chunking=True,
        idempotent=True,
        security_notes="Read-only; path is confined to the workspace.",
        dependencies=("dataframe", "pyarrow"),
        supported_dialects=("parquet",),
    ),
    ModuleSpec(
        name="save_csv",
        version="1.0.0",
        description="Save a DataFrame to a CSV file",
        constraints={"path": (Constraint(ConstraintKind.PATH),)},
        examples=({"path": "output.csv"},),
        supports_chunking=False,
        idempotent=False,
        security_notes="Writes a file.",
        side_effects=("writes a file",),
    ),
)


__all__ = ["MODULE_SPECS", "ModuleSpec"]
