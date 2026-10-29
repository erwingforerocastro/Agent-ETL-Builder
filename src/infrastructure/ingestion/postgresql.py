"""Read-only PostgreSQL table ingestion through the database port."""

from __future__ import annotations

from collections.abc import Iterator, Sequence

import pandas as pd
from psycopg import sql

from application.ports.database import DatabasePort, QueryResult
from domain.entities.ingestion import SourceIdentity
from infrastructure.database.identifiers import validate_identifier
from infrastructure.ingestion.identifiers import (
    credential_free_uri,
    source_identity_for_frame,
)


class PostgresSourceReader:
    """Reads PostgreSQL tables through read-only, server-side batches."""

    def __init__(
        self,
        database: DatabasePort,
        *,
        canonical_uri: str,
        schema: str = "public",
    ) -> None:
        if not canonical_uri.strip():
            raise ValueError("canonical_uri must not be blank")
        self._database = database
        self._canonical_uri = credential_free_uri(canonical_uri)
        self._schema = validate_identifier(schema, "schema")

    def read(
        self,
        *,
        table: str,
        columns: Sequence[str] = (),
    ) -> pd.DataFrame:
        """Read a whole table; use ``iter_chunks`` for large tables."""
        query = self._query(table, columns)
        with self._database.connect(read_only=True) as session:
            result = session.fetch_all(query)
        return _frame(result)

    def read_source(
        self,
        *,
        table: str,
        columns: Sequence[str] = (),
    ) -> tuple[pd.DataFrame, SourceIdentity]:
        """Read a table and return its stable identity with the frame."""
        frame = self.read(table=table, columns=columns)
        return frame, self.identity(frame, table=table, columns=columns)

    def iter_chunks(
        self,
        *,
        table: str,
        columns: Sequence[str] = (),
        chunk_size: int = 10_000,
    ) -> Iterator[pd.DataFrame]:
        """Yield server-side batches in deterministic row order."""
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        query = self._query(table, columns)
        with self._database.connect(read_only=True) as session:
            for batch in session.iter_batches(query, batch_size=chunk_size):
                yield _frame(batch)

    def identity(
        self,
        frame: pd.DataFrame,
        *,
        table: str,
        columns: Sequence[str] = (),
    ) -> SourceIdentity:
        """Build a stable identity for a table and column selection."""
        return source_identity_for_frame(
            frame,
            source_type="postgresql",
            canonical_uri=self._source_uri(table, columns),
        )

    def _query(self, table: str, columns: Sequence[str]) -> str:
        table_name = validate_identifier(table, "table")
        column_names = _column_names(columns)
        selection = (
            sql.SQL("*")
            if not column_names
            else sql.SQL(", ").join(sql.Identifier(column) for column in column_names)
        )
        query = sql.SQL("SELECT {} FROM {}").format(
            selection,
            sql.Identifier(self._schema, table_name),
        )
        return query.as_string(None)

    def _source_uri(self, table: str, columns: Sequence[str]) -> str:
        table_name = validate_identifier(table, "table")
        column_names = _column_names(columns)
        selected = ",".join(column_names) or "*"
        return f"{self._canonical_uri}#{self._schema}.{table_name}?columns={selected}"


def _column_names(columns: Sequence[str]) -> tuple[str, ...]:
    names = tuple(validate_identifier(column, "column") for column in columns)
    if len(set(names)) != len(names):
        raise ValueError("columns must be unique")
    return names


def _frame(result: QueryResult) -> pd.DataFrame:
    return pd.DataFrame.from_records(result.rows, columns=list(result.columns))


__all__ = ["PostgresSourceReader"]
