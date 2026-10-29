"""Static allowlist and metadata policy for approved modules."""

from collections.abc import Mapping
from dataclasses import dataclass

from application.registry.vocabulary import (
    CAST_ERROR_MODES,
    CAST_TARGET_TYPES,
    COLUMN_CASES,
    DATE_PARSE_MODES,
    FILL_METHODS,
    FILTER_OPERATORS,
    KEEP_POLICIES,
    TEXT_CASES,
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
        name="filter_rows",
        version="1.0.0",
        description="Keep rows that match one declarative predicate on a column.",
        constraints={
            "column": (Constraint(ConstraintKind.COLUMN_NAME),),
            "operator": (Constraint(ConstraintKind.ENUM, FILTER_OPERATORS),),
        },
        examples=({"column": "status", "operator": "equals", "value": "active"},),
        supports_chunking=True,
        idempotent=True,
        security_notes="DataFrame-only; literal predicates; no code or regex execution.",
    ),
    ModuleSpec(
        name="fill_missing_values",
        version="1.0.0",
        description="Fill null values in one column with a constant or summary value.",
        constraints={
            "column": (Constraint(ConstraintKind.COLUMN_NAME),),
            "method": (Constraint(ConstraintKind.ENUM, FILL_METHODS),),
        },
        examples=({"column": "amount", "method": "mean"},),
        supports_chunking=False,
        idempotent=True,
        security_notes="DataFrame-only; no I/O or code execution.",
    ),
    ModuleSpec(
        name="normalize_dates",
        version="1.0.0",
        description="Parse a date column and format it with a strftime pattern.",
        constraints={
            "column": (Constraint(ConstraintKind.COLUMN_NAME),),
            "output_format": (Constraint(ConstraintKind.NON_EMPTY),),
            "errors": (Constraint(ConstraintKind.ENUM, DATE_PARSE_MODES),),
        },
        examples=({"column": "created_at", "output_format": "%Y-%m-%d"},),
        supports_chunking=True,
        idempotent=True,
        security_notes="DataFrame-only; no I/O or code execution.",
    ),
    ModuleSpec(
        name="change_text_case",
        version="1.0.0",
        description="Change the case of text values in selected or all text columns.",
        constraints={
            "columns": (
                Constraint(ConstraintKind.NON_EMPTY),
                Constraint(ConstraintKind.TEXT_COLUMNS),
            ),
            "case": (Constraint(ConstraintKind.ENUM, TEXT_CASES),),
        },
        examples=({"columns": ["name"], "case": "lower"},),
        supports_chunking=True,
        idempotent=True,
        security_notes="DataFrame-only; no I/O or code execution.",
    ),
    ModuleSpec(
        name="replace_values",
        version="1.0.0",
        description="Replace exact text values with another string or with null.",
        constraints={
            "columns": (
                Constraint(ConstraintKind.NON_EMPTY),
                Constraint(ConstraintKind.TEXT_COLUMNS),
            )
        },
        examples=({"columns": ["status"], "old": "N/A", "new": None},),
        supports_chunking=True,
        idempotent=True,
        security_notes="DataFrame-only; exact literal matching; no regex execution.",
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
        description="Save a DataFrame to a CSV file atomically",
        constraints={"path": (Constraint(ConstraintKind.PATH),)},
        examples=({"path": "output.csv"},),
        supports_chunking=False,
        idempotent=False,
        security_notes="Writes a file atomically.",
        side_effects=("writes a file",),
    ),
    ModuleSpec(
        name="save_json",
        version="1.0.0",
        description="Save a DataFrame to a JSON array atomically",
        constraints={"path": (Constraint(ConstraintKind.PATH),)},
        examples=({"path": "output.json"},),
        supports_chunking=False,
        idempotent=False,
        security_notes="Writes a file atomically.",
        side_effects=("writes a file",),
    ),
    ModuleSpec(
        name="save_jsonl",
        version="1.0.0",
        description="Save a DataFrame to a JSON Lines file atomically",
        constraints={"path": (Constraint(ConstraintKind.PATH),)},
        examples=({"path": "output.jsonl"},),
        supports_chunking=False,
        idempotent=False,
        security_notes="Writes a file atomically.",
        side_effects=("writes a file",),
    ),
    ModuleSpec(
        name="save_parquet",
        version="1.0.0",
        description="Save a DataFrame to a Parquet file atomically",
        constraints={"path": (Constraint(ConstraintKind.PATH),)},
        examples=({"path": "output.parquet"},),
        supports_chunking=False,
        idempotent=False,
        security_notes="Writes a file atomically.",
        dependencies=("dataframe", "pyarrow"),
        side_effects=("writes a file",),
    ),
)


__all__ = ["MODULE_SPECS", "ModuleSpec"]
