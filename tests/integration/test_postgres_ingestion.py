"""Integration tests for read-only PostgreSQL source ingestion."""

from __future__ import annotations

import secrets

import pytest

from infrastructure.database.config import PostgresConfig
from infrastructure.database.postgres import PostgresDatabase
from infrastructure.ingestion.postgresql import PostgresSourceReader
from tests.integration.postgres_test_cluster import PostgresCluster


def _database(cluster: PostgresCluster) -> PostgresDatabase:
    return PostgresDatabase(
        PostgresConfig(
            dsn=cluster.dsn,
            sslmode="disable",
            connect_timeout_seconds=5,
            statement_timeout_ms=5_000,
        )
    )


def _schema_name() -> str:
    return f"agent_etl_ingest_{secrets.token_hex(4)}"


def _prepare(database: PostgresDatabase, schema: str, rows: int) -> None:
    with database.connect() as session:
        session.execute(f'CREATE SCHEMA "{schema}"')
        session.execute(
            f'CREATE TABLE "{schema}".people (id integer PRIMARY KEY, name text NOT NULL)'
        )
        session.execute_many(
            f'INSERT INTO "{schema}".people (id, name) VALUES (%s, %s)',
            [(index, f"person-{index}") for index in range(1, rows + 1)],
        )


def _drop(database: PostgresDatabase, schema: str) -> None:
    with database.connect() as session:
        session.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def test_read_source_returns_rows_and_stable_identity(
    postgres_cluster: PostgresCluster,
) -> None:
    database = _database(postgres_cluster)
    schema = _schema_name()
    _prepare(database, schema, rows=3)
    reader = PostgresSourceReader(
        database,
        canonical_uri=postgres_cluster.dsn,
        schema=schema,
    )
    try:
        frame, identity = reader.read_source(
            table="people",
            columns=("id", "name"),
        )
        _, same_identity = reader.read_source(
            table="people",
            columns=("id", "name"),
        )

        assert frame["id"].tolist() == [1, 2, 3]
        assert identity.row_count == 3
        assert identity.source_id == same_identity.source_id
        assert identity.content_hash.startswith("sha256:")
        assert identity.schema_hash.startswith("sha256:")
    finally:
        _drop(database, schema)


def test_iter_chunks_uses_server_side_batches(
    postgres_cluster: PostgresCluster,
) -> None:
    database = _database(postgres_cluster)
    schema = _schema_name()
    _prepare(database, schema, rows=5)
    reader = PostgresSourceReader(
        database,
        canonical_uri=postgres_cluster.dsn,
        schema=schema,
    )
    try:
        chunks = list(
            reader.iter_chunks(
                table="people",
                columns=("id",),
                chunk_size=2,
            )
        )
    finally:
        _drop(database, schema)

    assert [chunk["id"].tolist() for chunk in chunks] == [[1, 2], [3, 4], [5]]


def test_empty_table_preserves_columns(postgres_cluster: PostgresCluster) -> None:
    database = _database(postgres_cluster)
    schema = _schema_name()
    _prepare(database, schema, rows=0)
    reader = PostgresSourceReader(
        database,
        canonical_uri=postgres_cluster.dsn,
        schema=schema,
    )
    try:
        frame = reader.read(table="people")
        chunks = list(reader.iter_chunks(table="people", chunk_size=2))
    finally:
        _drop(database, schema)

    assert frame.empty
    assert frame.columns.tolist() == ["id", "name"]
    assert chunks == []


def test_different_tables_have_different_source_ids(
    postgres_cluster: PostgresCluster,
) -> None:
    database = _database(postgres_cluster)
    schema = _schema_name()
    _prepare(database, schema, rows=1)
    reader = PostgresSourceReader(
        database,
        canonical_uri=postgres_cluster.dsn,
        schema=schema,
    )
    try:
        frame, people_identity = reader.read_source(table="people")
        other_identity = reader.identity(frame, table="other_people")
    finally:
        _drop(database, schema)

    assert people_identity.source_id != other_identity.source_id


def test_invalid_identifier_is_rejected(postgres_cluster: PostgresCluster) -> None:
    database = _database(postgres_cluster)
    reader = PostgresSourceReader(
        database,
        canonical_uri=postgres_cluster.dsn,
        schema="public",
    )

    with pytest.raises(ValueError, match="table"):
        reader.read(table="people; DROP TABLE people")
