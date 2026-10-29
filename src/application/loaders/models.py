"""Validated load request and result models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

MAX_LOAD_BATCH_SIZE = 10_000


class LoadMode(StrEnum):
    """Supported PostgreSQL table load modes."""

    INSERT = "insert"
    UPSERT = "upsert"
    TRUNCATE_INSERT = "truncate_insert"


@dataclass(frozen=True, slots=True)
class LoadRequest:
    """One table load request."""

    table: str
    mode: LoadMode = LoadMode.INSERT
    schema: str = "public"
    conflict_columns: tuple[str, ...] = ()
    batch_size: int = 1_000

    def __post_init__(self) -> None:
        if not isinstance(self.table, str) or not self.table.strip():
            raise ValueError("table must not be blank")
        if not isinstance(self.schema, str) or not self.schema.strip():
            raise ValueError("schema must not be blank")
        try:
            mode = LoadMode(self.mode)
        except ValueError as exc:
            raise ValueError("mode must be insert, upsert, or truncate_insert") from exc
        object.__setattr__(self, "mode", mode)
        if (
            isinstance(self.batch_size, bool)
            or not isinstance(self.batch_size, int)
            or not 1 <= self.batch_size <= MAX_LOAD_BATCH_SIZE
        ):
            raise ValueError(f"batch_size must be between 1 and {MAX_LOAD_BATCH_SIZE}")
        columns = tuple(self.conflict_columns)
        object.__setattr__(self, "conflict_columns", columns)
        if any(not isinstance(column, str) or not column.strip() for column in columns):
            raise ValueError("conflict_columns must contain non-blank strings")
        if len(set(columns)) != len(columns):
            raise ValueError("conflict_columns must be unique")
        if mode is LoadMode.UPSERT:
            if not columns:
                raise ValueError("upsert requires at least one conflict column")
        elif columns:
            raise ValueError("conflict_columns are only valid for upsert")


@dataclass(frozen=True, slots=True)
class LoadResult:
    """Summary of one completed table load."""

    schema: str
    table: str
    mode: LoadMode
    row_count: int
    batch_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.schema, str) or not self.schema.strip():
            raise ValueError("schema must not be blank")
        if not isinstance(self.table, str) or not self.table.strip():
            raise ValueError("table must not be blank")
        try:
            mode = LoadMode(self.mode)
        except ValueError as exc:
            raise ValueError("mode must be insert, upsert, or truncate_insert") from exc
        object.__setattr__(self, "mode", mode)
        if isinstance(self.row_count, bool) or not isinstance(self.row_count, int):
            raise ValueError("row_count must be a non-negative integer")
        if isinstance(self.batch_count, bool) or not isinstance(self.batch_count, int):
            raise ValueError("batch_count must be a non-negative integer")
        if self.row_count < 0 or self.batch_count < 0:
            raise ValueError("row_count and batch_count must not be negative")


__all__ = ["MAX_LOAD_BATCH_SIZE", "LoadMode", "LoadRequest", "LoadResult"]
