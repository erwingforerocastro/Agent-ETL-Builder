"""Integration tests for transactional PostgreSQL table loading."""

from __future__ import annotations

import secrets

import pandas as pd
import pytest
from psycopg import sql

from application.loaders.models import LoadMode, LoadRequest
from domain.errors import LoadError
from infrastructure.database.config import PostgresConfig
from infrastructure.database.postgres import PostgresDatabase
from infrastructure.loaders.postgresql import PostgresTableLoader
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
    return f"agent_etl_load_{secrets.token_hex(4)}"


def _prepare(database: PostgresDatabase, schema: str) -> None:
    with database.connect() as session:
        session.execute(f'CREATE SCHEMA "{schema}"')
        session.execute(
            f'CREATE TABLE "{schema}".people '
            "(id integer PRIMARY KEY, name text NOT NULL, note text)"
        )


def _drop(database: PostgresDatabase, schema: str) -> None:
    with database.connect() as session:
        session.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def _rows(database: PostgresDatabase, schema: str) -> list[tuple[object, ...]]:
    query = sql.SQL("SELECT id, name, note FROM {} ORDER BY id").format(
        sql.Identifier(schema, "people")
    )
    with database.connect(read_only=True) as session:
        result = session.fetch_all(query.as_string(None))
    return list(result.rows)


def test_insert_appends_rows(postgres_cluster: PostgresCluster) -> None:
    database = _database(postgres_cluster)
    schema = _schema_name()
    _prepare(database, schema)
    loader = PostgresTableLoader(database)
    try:
        result = loader.load(
            pd.DataFrame({"id": [1, 2], "name": ["Ada", "Bob"]}),
            LoadRequest(schema=schema, table="people"),
        )

        assert result.row_count == 2
        assert result.batch_count == 1
        assert _rows(database, schema) == [(1, "Ada", None), (2, "Bob", None)]
    finally:
        _drop(database, schema)


def test_upsert_updates_and_inserts_rows(postgres_cluster: PostgresCluster) -> None:
    database = _database(postgres_cluster)
    schema = _schema_name()
    _prepare(database, schema)
    loader = PostgresTableLoader(database)
    try:
        loader.load(
            pd.DataFrame({"id": [1, 2], "name": ["Ada", "Bob"]}),
            LoadRequest(schema=schema, table="people"),
        )
        result = loader.load(
            pd.DataFrame({"id": [1, 3], "name": ["Ada Lovelace", "Cyd"]}),
            LoadRequest(
                schema=schema,
                table="people",
                mode=LoadMode.UPSERT,
                conflict_columns=("id",),
            ),
        )

        assert result.row_count == 2
        assert _rows(database, schema) == [
            (1, "Ada Lovelace", None),
            (2, "Bob", None),
            (3, "Cyd", None),
        ]
    finally:
        _drop(database, schema)


def test_truncate_insert_replaces_table_contents(postgres_cluster: PostgresCluster) -> None:
    database = _database(postgres_cluster)
    schema = _schema_name()
    _prepare(database, schema)
    loader = PostgresTableLoader(database)
    try:
        loader.load(
            pd.DataFrame({"id": [1, 2], "name": ["Ada", "Bob"]}),
            LoadRequest(schema=schema, table="people"),
        )
        loader.load(
            pd.DataFrame({"id": [9], "name": ["Zoe"]}),
            LoadRequest(
                schema=schema,
                table="people",
                mode=LoadMode.TRUNCATE_INSERT,
            ),
        )

        assert _rows(database, schema) == [(9, "Zoe", None)]
    finally:
        _drop(database, schema)


def test_batch_failure_rolls_back_the_whole_load(postgres_cluster: PostgresCluster) -> None:
    database = _database(postgres_cluster)
    schema = _schema_name()
    _prepare(database, schema)
    loader = PostgresTableLoader(database)
    try:
        loader.load(
            pd.DataFrame({"id": [1], "name": ["Ada"]}),
            LoadRequest(schema=schema, table="people"),
        )

        with pytest.raises(LoadError):
            loader.load(
                pd.DataFrame({"id": [2, 1], "name": ["Bob", "Grace"]}),
                LoadRequest(schema=schema, table="people", batch_size=1),
            )

        assert _rows(database, schema) == [(1, "Ada", None)]
    finally:
        _drop(database, schema)


def test_empty_truncate_insert_clears_the_table(postgres_cluster: PostgresCluster) -> None:
    database = _database(postgres_cluster)
    schema = _schema_name()
    _prepare(database, schema)
    loader = PostgresTableLoader(database)
    try:
        loader.load(
            pd.DataFrame({"id": [1], "name": ["Ada"]}),
            LoadRequest(schema=schema, table="people"),
        )
        empty = pd.DataFrame(
            {
                "id": pd.Series([], dtype="Int64"),
                "name": pd.Series([], dtype="string"),
                "note": pd.Series([], dtype="string"),
            }
        )
        result = loader.load(
            empty,
            LoadRequest(
                schema=schema,
                table="people",
                mode=LoadMode.TRUNCATE_INSERT,
            ),
        )

        assert result.row_count == 0
        assert _rows(database, schema) == []
    finally:
        _drop(database, schema)
