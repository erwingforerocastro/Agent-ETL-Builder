"""Database access contracts for SQL-backed ingestion and loading."""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class QueryResult:
    """One query result. ``truncated`` means ``max_rows`` hid additional rows."""

    columns: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]
    truncated: bool = False


class DatabaseSessionPort(Protocol):
    """One transaction-scoped database session."""

    def fetch_all(
        self,
        sql: str,
        params: Sequence[object] = (),
        *,
        max_rows: int | None = None,
    ) -> QueryResult:
        """Run a parameterized query and return its columns and rows."""
        ...

    def execute(self, sql: str, params: Sequence[object] = ()) -> int:
        """Run a parameterized statement and return its affected row count."""
        ...

    def execute_many(self, sql: str, rows: Sequence[Sequence[object]]) -> int:
        """Run one parameterized statement for each supplied row set."""
        ...


class DatabasePort(Protocol):
    """Opens read-only or writable database sessions."""

    def connect(
        self,
        *,
        read_only: bool = False,
    ) -> AbstractContextManager[DatabaseSessionPort]:
        """Open one session that commits on success and rolls back on error."""
        ...


__all__ = ["DatabasePort", "DatabaseSessionPort", "QueryResult"]
