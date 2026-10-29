"""PostgreSQL adapter built on psycopg."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any, cast
from uuid import uuid4

import psycopg
from psycopg import Connection
from psycopg.rows import tuple_row

from application.ports.database import QueryResult
from domain.errors import IngestionError, LoadError
from infrastructure.database.config import PostgresConfig

ConnectionFactory = Callable[..., Connection[Any]]


class PostgresDatabase:
    """Opens transaction-scoped PostgreSQL sessions with safe defaults."""

    def __init__(
        self,
        config: PostgresConfig,
        *,
        connector: ConnectionFactory | None = None,
    ) -> None:
        self._config = config
        self._connector = connector or cast(ConnectionFactory, psycopg.connect)

    @contextmanager
    def connect(self, *, read_only: bool = False) -> Iterator[PostgresSession]:
        options: dict[str, object] = {
            "autocommit": False,
            "row_factory": tuple_row,
            "sslmode": self._config.sslmode,
            "connect_timeout": self._config.connect_timeout_seconds,
            "application_name": self._config.application_name,
        }
        if self._config.sslrootcert is not None:
            options["sslrootcert"] = self._config.sslrootcert
        try:
            with self._connector(self._config.dsn, **options) as connection:
                self._prepare(connection, read_only=read_only)
                yield PostgresSession(connection, read_only=read_only)
        except (IngestionError, LoadError):
            raise
        except psycopg.Error as exc:
            raise _database_error(read_only=read_only, exc=exc) from exc

    def _prepare(self, connection: Connection[Any], *, read_only: bool) -> None:
        with connection.cursor() as cursor:
            if read_only:
                cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (str(self._config.statement_timeout_ms),),
            )


class PostgresSession:
    """One transaction-scoped session that parameterizes every statement."""

    def __init__(self, connection: Connection[Any], *, read_only: bool) -> None:
        self._connection = connection
        self._read_only = read_only

    def fetch_all(
        self,
        sql: str,
        params: Sequence[object] = (),
        *,
        max_rows: int | None = None,
    ) -> QueryResult:
        if max_rows is not None and max_rows < 0:
            raise ValueError("max_rows must not be negative")
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(sql, params)
                columns = tuple(column.name for column in cursor.description or ())
                if max_rows is None:
                    rows = cursor.fetchall()
                    truncated = False
                else:
                    rows = cursor.fetchmany(max_rows + 1)
                    truncated = len(rows) > max_rows
                    if truncated:
                        rows = rows[:max_rows]
                return QueryResult(
                    columns=columns,
                    rows=tuple(tuple(row) for row in rows),
                    truncated=truncated,
                )
        except psycopg.Error as exc:
            raise self._error(exc) from exc

    def execute(self, sql: str, params: Sequence[object] = ()) -> int:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(sql, params)
                return cursor.rowcount
        except psycopg.Error as exc:
            raise self._error(exc) from exc

    def execute_many(self, sql: str, rows: Sequence[Sequence[object]]) -> int:
        if not rows:
            return 0
        try:
            with self._connection.cursor() as cursor:
                cursor.executemany(sql, rows)
                return cursor.rowcount
        except psycopg.Error as exc:
            raise self._error(exc) from exc

    def iter_batches(
        self,
        sql: str,
        params: Sequence[object] = (),
        *,
        batch_size: int,
    ) -> Iterator[QueryResult]:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        try:
            with self._connection.cursor(name=f"agent_etl_{uuid4().hex}") as cursor:
                cursor.execute(sql, params)
                columns = tuple(column.name for column in cursor.description or ())
                while True:
                    rows = cursor.fetchmany(batch_size)
                    if not rows:
                        break
                    yield QueryResult(
                        columns=columns,
                        rows=tuple(tuple(row) for row in rows),
                    )
        except psycopg.Error as exc:
            raise self._error(exc) from exc

    def _error(self, exc: psycopg.Error) -> IngestionError | LoadError:
        return _database_error(read_only=self._read_only, exc=exc)


def _database_error(
    *,
    read_only: bool,
    exc: psycopg.Error,
) -> IngestionError | LoadError:
    context: dict[str, object] = {"error_type": type(exc).__name__}
    if exc.sqlstate is not None:
        context["sqlstate"] = exc.sqlstate
    retryable = _is_retryable(exc)
    if read_only:
        return IngestionError(
            code="DATABASE_READ_FAILED",
            message="Database read failed",
            module=__name__,
            retryable=retryable,
            context=context,
        )
    return LoadError(
        code="DATABASE_WRITE_FAILED",
        message="Database write failed",
        module=__name__,
        retryable=retryable,
        context=context,
    )


def _is_retryable(exc: psycopg.Error) -> bool:
    """Retry connection and transaction-rollback failures, not auth or data errors."""
    if not isinstance(exc, psycopg.OperationalError):
        return False
    return exc.sqlstate is None or exc.sqlstate.startswith(("08", "40"))


__all__ = ["ConnectionFactory", "PostgresDatabase", "PostgresSession"]
