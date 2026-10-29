"""Unit tests for PostgreSQL source reads through the database port."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager

import pytest

from application.ports.database import QueryResult
from domain.entities.ingestion import SourceIdentity
from infrastructure.ingestion.identifiers import source_id_for
from infrastructure.ingestion.postgresql import PostgresSourceReader


class _FakeSession:
    def __init__(
        self,
        *,
        columns: Sequence[str],
        rows: Sequence[tuple[object, ...]],
        batches: Sequence[Sequence[tuple[object, ...]]] | None = None,
    ) -> None:
        self.columns = tuple(columns)
        self.rows = tuple(rows)
        self.batches = tuple(tuple(batch) for batch in (batches or ()))
        self.queries: list[str] = []
        self.batch_sizes: list[int] = []

    def fetch_all(
        self,
        sql: str,
        params: Sequence[object] = (),
        *,
        max_rows: int | None = None,
    ) -> QueryResult:
        del params, max_rows
        self.queries.append(sql)
        return QueryResult(columns=self.columns, rows=self.rows)

    def execute(self, sql: str, params: Sequence[object] = ()) -> int:
        raise AssertionError("writes must not be used for source reads")

    def execute_many(self, sql: str, rows: Sequence[Sequence[object]]) -> int:
        raise AssertionError("writes must not be used for source reads")

    def iter_batches(
        self,
        sql: str,
        params: Sequence[object] = (),
        *,
        batch_size: int,
    ) -> Iterator[QueryResult]:
        del params
        self.queries.append(sql)
        self.batch_sizes.append(batch_size)
        for batch in self.batches:
            yield QueryResult(columns=self.columns, rows=batch)


class _FakeDatabase:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session
        self.read_only_modes: list[bool] = []

    @contextmanager
    def connect(self, *, read_only: bool = False) -> Iterator[_FakeSession]:
        self.read_only_modes.append(read_only)
        yield self.session


def _reader(
    database: _FakeDatabase,
    *,
    canonical_uri: str = "postgresql://localhost:5432/warehouse",
    schema: str = "public",
) -> PostgresSourceReader:
    return PostgresSourceReader(database, canonical_uri=canonical_uri, schema=schema)


def _session(
    *,
    columns: Sequence[str] = ("id", "name"),
    rows: Sequence[tuple[object, ...]] = ((1, "Ada"), (2, "Bob")),
) -> _FakeSession:
    return _FakeSession(columns=columns, rows=rows)


def test_read_uses_read_only_session_and_quoted_identifiers() -> None:
    session = _session()
    database = _FakeDatabase(session)
    reader = _reader(database)

    frame = reader.read(table="people", columns=("id", "name"))

    assert database.read_only_modes == [True]
    assert session.queries == ['SELECT "id", "name" FROM "public"."people"']
    assert frame.to_dict("records") == [
        {"id": 1, "name": "Ada"},
        {"id": 2, "name": "Bob"},
    ]


def test_read_without_columns_selects_all_columns() -> None:
    session = _session()
    database = _FakeDatabase(session)
    reader = _reader(database)

    reader.read(table="people")

    assert session.queries == ['SELECT * FROM "public"."people"']


def test_read_source_returns_a_stable_credential_free_identity() -> None:
    session = _session()
    database = _FakeDatabase(session)
    reader = _reader(
        database,
        canonical_uri="postgresql://user:secret@localhost:5432/warehouse",
    )

    _frame, identity = reader.read_source(table="people", columns=("id", "name"))
    expected_source_id = source_id_for(
        "postgresql",
        "postgresql://localhost:5432/warehouse#public.people?columns=id,name",
    )

    assert isinstance(identity, SourceIdentity)
    assert identity.source_id == expected_source_id
    assert identity.row_count == 2
    assert "secret" not in identity.source_id


def test_iter_chunks_uses_server_side_batches() -> None:
    session = _FakeSession(
        columns=("id",),
        rows=(),
        batches=(((1,),), ((2,), (3,))),
    )
    database = _FakeDatabase(session)
    reader = _reader(database)

    chunks = list(reader.iter_chunks(table="people", columns=("id",), chunk_size=2))

    assert [chunk["id"].tolist() for chunk in chunks] == [[1], [2, 3]]
    assert database.read_only_modes == [True]
    assert session.batch_sizes == [2]
    assert session.queries == ['SELECT "id" FROM "public"."people"']


def test_empty_result_preserves_columns() -> None:
    session = _session(rows=())
    database = _FakeDatabase(session)
    reader = _reader(database)

    frame = reader.read(table="people")

    assert frame.empty
    assert frame.columns.tolist() == ["id", "name"]


@pytest.mark.parametrize(
    ("table", "columns", "match"),
    [
        ("people; DROP TABLE people", (), "table"),
        ("pg_catalog", (), "reserved"),
        ("people", ("id", "id"), "unique"),
        ("people", ("id; DROP",), "column"),
        ("people", ("",), "column"),
    ],
)
def test_invalid_identifiers_are_rejected_before_database_access(
    table: str,
    columns: tuple[str, ...],
    match: str,
) -> None:
    session = _session()
    database = _FakeDatabase(session)
    reader = _reader(database)

    with pytest.raises(ValueError, match=match):
        reader.read(table=table, columns=columns)

    assert database.read_only_modes == []


def test_invalid_chunk_size_is_rejected() -> None:
    session = _session()
    database = _FakeDatabase(session)
    reader = _reader(database)

    with pytest.raises(ValueError, match="chunk_size"):
        list(reader.iter_chunks(table="people", chunk_size=0))
