"""Integration tests for PostgreSQL connectivity on a temporary cluster."""

from __future__ import annotations

import secrets
from pathlib import Path

import pytest

from domain.errors import IngestionError, LoadError
from infrastructure.database.config import PostgresConfig, SslMode
from infrastructure.database.postgres import PostgresDatabase
from tests.integration.postgres_test_cluster import PostgresCluster as _Cluster


def _database(cluster: _Cluster, *, sslmode: SslMode = "disable") -> PostgresDatabase:
    return PostgresDatabase(
        PostgresConfig(
            dsn=cluster.dsn,
            sslmode=sslmode,
            connect_timeout_seconds=5,
            statement_timeout_ms=5_000,
        )
    )


def _schema_name() -> str:
    return f"agent_etl_test_{secrets.token_hex(4)}"


def _prepare(database: PostgresDatabase, schema: str) -> None:
    with database.connect() as session:
        session.execute(f'CREATE SCHEMA "{schema}"')
        session.execute(
            f'CREATE TABLE "{schema}".people (id integer PRIMARY KEY, name text NOT NULL)'
        )


def _drop(database: PostgresDatabase, schema: str) -> None:
    with database.connect() as session:
        session.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def _insert_duplicate(database: PostgresDatabase, schema: str) -> None:
    with database.connect() as session:
        session.execute(
            f'INSERT INTO "{schema}".people (id, name) VALUES (%s, %s)',
            (1, "Ada"),
        )
        session.execute(
            f'INSERT INTO "{schema}".people (id, name) VALUES (%s, %s)',
            (1, "Bob"),
        )


def test_parameterized_read_write_in_temporary_schema(postgres_cluster: _Cluster) -> None:
    database = _database(postgres_cluster)
    schema = _schema_name()
    payload = "O'Brien; DROP TABLE people; --"
    _prepare(database, schema)
    try:
        with database.connect() as session:
            assert (
                session.execute(
                    f'INSERT INTO "{schema}".people (id, name) VALUES (%s, %s)',
                    (1, payload),
                )
                == 1
            )
            result = session.fetch_all(
                f'SELECT id, name FROM "{schema}".people WHERE name = %s',
                (payload,),
            )
        assert result.columns == ("id", "name")
        assert result.rows == ((1, payload),)
    finally:
        _drop(database, schema)


def test_read_only_session_rejects_writes(postgres_cluster: _Cluster) -> None:
    database = _database(postgres_cluster)
    schema = _schema_name()
    _prepare(database, schema)
    try:
        with (
            pytest.raises(IngestionError) as captured,
            database.connect(read_only=True) as session,
        ):
            session.execute(
                f'INSERT INTO "{schema}".people (id, name) VALUES (%s, %s)',
                (1, "Ada"),
            )
        assert captured.value.code == "DATABASE_READ_FAILED"

        with database.connect(read_only=True) as session:
            result = session.fetch_all(f'SELECT count(*) FROM "{schema}".people')
        assert result.rows == ((0,),)
    finally:
        _drop(database, schema)


def test_failed_write_rolls_back_transaction(postgres_cluster: _Cluster) -> None:
    database = _database(postgres_cluster)
    schema = _schema_name()
    _prepare(database, schema)
    try:
        with pytest.raises(LoadError):
            _insert_duplicate(database, schema)

        with database.connect(read_only=True) as session:
            result = session.fetch_all(f'SELECT count(*) FROM "{schema}".people')
        assert result.rows == ((0,),)
    finally:
        _drop(database, schema)


def test_statement_timeout_is_enforced(postgres_cluster: _Cluster) -> None:
    database = PostgresDatabase(
        PostgresConfig(
            dsn=postgres_cluster.dsn,
            sslmode="disable",
            statement_timeout_ms=100,
        )
    )

    with (
        pytest.raises(IngestionError) as captured,
        database.connect(read_only=True) as session,
    ):
        session.fetch_all("SELECT pg_sleep(1)")

    assert captured.value.code == "DATABASE_READ_FAILED"
    assert captured.value.context.get("sqlstate") == "57014"


def _require_tls(cluster: _Cluster) -> Path:
    if cluster.cert_path is None:
        pytest.skip("OpenSSL is not available to create a test certificate")
    return cluster.cert_path


def test_tls_require_connects(postgres_cluster: _Cluster) -> None:
    _require_tls(postgres_cluster)
    database = _database(postgres_cluster, sslmode="require")

    with database.connect(read_only=True) as session:
        result = session.fetch_all("SELECT 1")

    assert result.rows == ((1,),)


def test_tls_verify_full_connects_with_root_certificate(
    postgres_cluster: _Cluster,
) -> None:
    cert_path = _require_tls(postgres_cluster)
    database = PostgresDatabase(
        PostgresConfig(
            dsn=postgres_cluster.dsn,
            sslmode="verify-full",
            sslrootcert=str(cert_path),
        )
    )

    with database.connect(read_only=True) as session:
        result = session.fetch_all("SELECT 1")

    assert result.rows == ((1,),)


def test_tls_verify_full_rejects_untrusted_certificate(
    postgres_cluster: _Cluster,
) -> None:
    _require_tls(postgres_cluster)
    database = _database(postgres_cluster, sslmode="verify-full")

    with pytest.raises(IngestionError) as captured, database.connect(read_only=True):
        pass

    assert captured.value.code == "DATABASE_READ_FAILED"


def test_tls_require_is_enforced_without_server_tls(
    postgres_cluster: _Cluster,
) -> None:
    if postgres_cluster.cert_path is not None:
        pytest.skip("test cluster has TLS enabled")
    database = _database(postgres_cluster, sslmode="require")

    with pytest.raises(IngestionError) as captured, database.connect(read_only=True):
        pass

    assert captured.value.code == "DATABASE_READ_FAILED"
