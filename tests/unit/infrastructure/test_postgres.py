from __future__ import annotations

from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any, Literal, cast

import psycopg
import pytest
from psycopg.rows import tuple_row

from domain.errors import IngestionError, LoadError
from infrastructure.database.config import PostgresConfig, SslMode
from infrastructure.database.postgres import ConnectionFactory, PostgresDatabase

_DSN = "postgresql://user:secret@localhost:5432/warehouse"


class _FakeCursor:
    def __init__(self, connection: _FakeConnection) -> None:
        self._connection = connection
        self._rows: list[tuple[object, ...]] = []
        self.rowcount = -1
        self.description: tuple[SimpleNamespace, ...] | None = None

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def execute(self, sql: str, params: Sequence[object] = ()) -> None:
        self._connection.record(sql, tuple(params))
        self._connection.raise_for(sql)
        self._rows = list(self._connection.rows)
        self.rowcount = self._connection.rowcount
        self.description = (
            tuple(SimpleNamespace(name=name) for name in self._connection.columns) or None
        )

    def executemany(
        self,
        sql: str,
        rows: Sequence[Sequence[object]],
    ) -> None:
        self._connection.record(sql, tuple(tuple(row) for row in rows))
        self._connection.raise_for(sql)
        self.rowcount = self._connection.rowcount

    def fetchall(self) -> list[tuple[object, ...]]:
        return list(self._rows)

    def fetchmany(self, size: int) -> list[tuple[object, ...]]:
        return list(self._rows[:size])


class _FakeConnection:
    def __init__(
        self,
        *,
        rows: Sequence[tuple[object, ...]] = (),
        columns: Sequence[str] = (),
        rowcount: int = 1,
        error: Exception | None = None,
        error_on_sql: str | None = None,
    ) -> None:
        self.rows = tuple(rows)
        self.columns = tuple(columns)
        self.rowcount = rowcount
        self.error = error
        self.error_on_sql = error_on_sql
        self.statements: list[tuple[str, object]] = []
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> Literal[False]:
        if exc_type is None:
            self.committed = True
        else:
            self.rolled_back = True
        self.closed = True
        return False

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def record(self, sql: str, params: object) -> None:
        self.statements.append((sql, params))

    def raise_for(self, sql: str) -> None:
        if self.error is None:
            return
        if self.error_on_sql is None or self.error_on_sql in sql:
            raise self.error


def _database(
    connection: _FakeConnection,
    *,
    config: PostgresConfig | None = None,
) -> tuple[PostgresDatabase, list[tuple[str, dict[str, object]]]]:
    calls: list[tuple[str, dict[str, object]]] = []

    def connector(dsn: str, **kwargs: object) -> Any:
        calls.append((dsn, kwargs))
        return connection

    database = PostgresDatabase(
        config or PostgresConfig(dsn=_DSN),
        connector=cast(ConnectionFactory, connector),
    )
    return database, calls


def test_connect_uses_tls_timeouts_and_commits() -> None:
    connection = _FakeConnection()
    database, calls = _database(connection)

    with database.connect() as session:
        assert session.execute("SELECT %s", ("value",)) == 1

    assert len(calls) == 1
    dsn, kwargs = calls[0]
    assert dsn == _DSN
    assert kwargs["sslmode"] == "prefer"
    assert "sslrootcert" not in kwargs
    assert kwargs["connect_timeout"] == 10
    assert kwargs["application_name"] == "agent-etl-builder"
    assert kwargs["autocommit"] is False
    assert kwargs["row_factory"] is tuple_row
    assert connection.committed is True
    assert connection.rolled_back is False
    assert connection.closed is True


def test_connect_passes_root_certificate_when_configured() -> None:
    connection = _FakeConnection()
    database, calls = _database(
        connection,
        config=PostgresConfig(
            dsn=_DSN,
            sslmode="verify-full",
            sslrootcert="C:/certs/root.crt",
        ),
    )

    with database.connect(read_only=True):
        pass

    _, kwargs = calls[0]
    assert kwargs["sslmode"] == "verify-full"
    assert kwargs["sslrootcert"] == "C:/certs/root.crt"


def test_connect_rolls_back_when_session_body_raises() -> None:
    connection = _FakeConnection()
    database, _ = _database(connection)

    with pytest.raises(RuntimeError), database.connect():
        raise RuntimeError("boom")

    assert connection.committed is False
    assert connection.rolled_back is True
    assert connection.closed is True


def test_read_only_session_sets_transaction_and_statement_timeout() -> None:
    connection = _FakeConnection()
    database, _ = _database(
        connection,
        config=PostgresConfig(dsn=_DSN, statement_timeout_ms=1_500),
    )

    with database.connect(read_only=True) as session:
        session.execute("SELECT 1")

    assert connection.statements[0] == ("SET TRANSACTION READ ONLY", ())
    assert connection.statements[1] == (
        "SELECT set_config('statement_timeout', %s, true)",
        ("1500",),
    )


def test_fetch_all_returns_columns_rows_and_truncation() -> None:
    connection = _FakeConnection(
        rows=[(1, "Ada"), (2, "Bob"), (3, "Cyd")],
        columns=("id", "name"),
    )
    database, _ = _database(connection)

    with database.connect(read_only=True) as session:
        result = session.fetch_all("SELECT id, name FROM people", max_rows=2)

    assert result.columns == ("id", "name")
    assert result.rows == ((1, "Ada"), (2, "Bob"))
    assert result.truncated is True


def test_fetch_all_without_limit_returns_every_row() -> None:
    connection = _FakeConnection(rows=[(1,), (2,)], columns=("id",))
    database, _ = _database(connection)

    with database.connect(read_only=True) as session:
        result = session.fetch_all("SELECT id FROM people")

    assert result.rows == ((1,), (2,))
    assert result.truncated is False


def test_execute_and_execute_many_return_rowcounts() -> None:
    connection = _FakeConnection(rowcount=4)
    database, _ = _database(connection)

    with database.connect() as session:
        assert session.execute("INSERT INTO people VALUES (%s)", (1,)) == 4
        assert session.execute_many("INSERT INTO people VALUES (%s)", [(2,), (3,)]) == 4
        assert session.execute_many("INSERT INTO people VALUES (%s)", []) == 0

    assert len(connection.statements) == 3


def test_fetch_all_rejects_negative_max_rows() -> None:
    connection = _FakeConnection()
    database, _ = _database(connection)

    with database.connect(read_only=True) as session, pytest.raises(ValueError, match="max_rows"):
        session.fetch_all("SELECT 1", max_rows=-1)


def test_read_error_is_sanitized_and_retryable() -> None:
    connection = _FakeConnection(
        error=psycopg.OperationalError(
            "password=secret password authentication failed for user 'secret'"
        ),
        error_on_sql="FROM people",
    )
    database, _ = _database(connection)

    with pytest.raises(IngestionError) as captured, database.connect(read_only=True) as session:
        session.fetch_all("SELECT * FROM people WHERE name = %s", ("secret-value",))

    error = captured.value
    assert error.code == "DATABASE_READ_FAILED"
    assert error.retryable is True
    assert error.context == {"error_type": "OperationalError"}
    assert "secret" not in str(error)
    assert "secret" not in repr(error.context)


def test_write_error_includes_sqlstate_and_is_not_retryable() -> None:
    connection = _FakeConnection(
        error=psycopg.errors.UniqueViolation("duplicate key value: secret"),
        error_on_sql="INSERT",
    )
    database, _ = _database(connection)

    with pytest.raises(LoadError) as captured, database.connect() as session:
        session.execute("INSERT INTO people VALUES (%s)", ("secret",))

    error = captured.value
    assert error.code == "DATABASE_WRITE_FAILED"
    assert error.retryable is False
    assert error.context == {
        "error_type": "UniqueViolation",
        "sqlstate": "23505",
    }
    assert "secret" not in repr(error.context)


def test_authentication_failure_is_not_retryable() -> None:
    connection = _FakeConnection(
        error=psycopg.errors.InvalidPassword("password authentication failed: secret"),
        error_on_sql="FROM people",
    )
    database, _ = _database(connection)

    with pytest.raises(IngestionError) as captured, database.connect(read_only=True) as session:
        session.fetch_all("SELECT * FROM people")

    assert captured.value.retryable is False
    assert captured.value.context["sqlstate"] == "28P01"
    assert "secret" not in repr(captured.value.context)


@pytest.mark.parametrize(("read_only", "error_type"), [(True, IngestionError), (False, LoadError)])
def test_connection_failure_is_wrapped_by_session_mode(
    read_only: bool,
    error_type: type[IngestionError] | type[LoadError],
) -> None:
    def connector(dsn: str, **kwargs: object) -> Any:
        del dsn, kwargs
        raise psycopg.OperationalError("could not connect: secret")

    database = PostgresDatabase(
        PostgresConfig(dsn=_DSN),
        connector=cast(ConnectionFactory, connector),
    )

    with pytest.raises(error_type) as captured, database.connect(read_only=read_only):
        pass

    assert captured.value.retryable is True
    assert "secret" not in str(captured.value)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"dsn": " "}, "dsn must not be blank"),
        ({"dsn": _DSN, "sslmode": cast(SslMode, "bogus")}, "unsupported sslmode"),
        ({"dsn": _DSN, "sslrootcert": " "}, "sslrootcert"),
        ({"dsn": _DSN, "connect_timeout_seconds": 0}, "connect_timeout_seconds"),
        ({"dsn": _DSN, "statement_timeout_ms": 0}, "statement_timeout_ms"),
        ({"dsn": _DSN, "application_name": " "}, "application_name"),
    ],
)
def test_postgres_config_rejects_invalid_values(
    kwargs: dict[str, object],
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        PostgresConfig(**kwargs)  # type: ignore[arg-type]


def test_postgres_config_repr_hides_dsn() -> None:
    config = PostgresConfig(dsn="postgresql://user:secret@localhost/warehouse")

    assert "secret" not in repr(config)
