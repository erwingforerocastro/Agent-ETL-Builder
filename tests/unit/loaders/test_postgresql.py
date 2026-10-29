"""Unit tests for the transactional PostgreSQL table loader."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from typing import cast

import pandas as pd
import pytest

from application.loaders.models import LoadMode, LoadRequest
from application.ports.database import DatabasePort
from domain.errors import LoadError
from infrastructure.loaders.postgresql import PostgresTableLoader


class _Session:
    def __init__(self, calls: list[tuple[str, str, object]]) -> None:
        self._calls = calls

    def execute(self, sql: str, params: Sequence[object] = ()) -> int:
        self._calls.append(("execute", sql, tuple(params)))
        return 1

    def execute_many(self, sql: str, rows: Sequence[Sequence[object]]) -> int:
        self._calls.append(("execute_many", sql, list(rows)))
        return len(rows)


class _Database:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object]] = []
        self.sessions = 0
        self.read_only: list[bool] = []

    @contextmanager
    def connect(self, *, read_only: bool = False) -> Iterator[_Session]:
        self.sessions += 1
        self.read_only.append(read_only)
        yield _Session(self.calls)


def _loader() -> tuple[PostgresTableLoader, _Database]:
    database = _Database()
    return PostgresTableLoader(cast(DatabasePort, database)), database


def test_insert_batches_rows_and_preserves_order() -> None:
    loader, database = _loader()
    frame = pd.DataFrame({"id": [1, 2], "name": ["Ada", "Bob"]})

    result = loader.load(frame, LoadRequest(table="people", batch_size=1))

    assert result.row_count == 2
    assert result.batch_count == 2
    assert database.sessions == 1
    assert database.read_only == [False]
    assert database.calls[0][1] == ('INSERT INTO "public"."people" ("id", "name") VALUES (%s, %s)')
    assert database.calls[0][2] == [(1, "Ada")]
    assert database.calls[1][2] == [(2, "Bob")]


def test_upsert_updates_non_conflict_columns() -> None:
    loader, database = _loader()
    frame = pd.DataFrame({"id": [1], "name": ["Ada"]})

    loader.load(
        frame,
        LoadRequest(
            table="people",
            mode=LoadMode.UPSERT,
            conflict_columns=("id",),
        ),
    )

    sql = database.calls[0][1]
    assert 'ON CONFLICT ("id")' in sql
    assert 'DO UPDATE SET "name" = EXCLUDED."name"' in sql


def test_upsert_with_only_conflict_columns_does_nothing() -> None:
    loader, database = _loader()
    frame = pd.DataFrame({"id": [1]})

    loader.load(
        frame,
        LoadRequest(
            table="people",
            mode=LoadMode.UPSERT,
            conflict_columns=("id",),
        ),
    )

    sql = database.calls[0][1]
    assert sql.endswith('ON CONFLICT ("id") DO NOTHING')


def test_truncate_insert_truncates_before_inserting() -> None:
    loader, database = _loader()
    frame = pd.DataFrame({"id": [1, 2], "name": ["Ada", "Bob"]})

    result = loader.load(
        frame,
        LoadRequest(table="people", mode=LoadMode.TRUNCATE_INSERT, batch_size=2),
    )

    assert result.row_count == 2
    assert result.batch_count == 1
    assert database.calls[0] == ("execute", 'TRUNCATE TABLE "public"."people"', ())
    assert database.calls[1][0] == "execute_many"


def test_empty_insert_is_a_no_op() -> None:
    loader, database = _loader()
    frame = pd.DataFrame(
        {
            "id": pd.Series([], dtype="Int64"),
            "name": pd.Series([], dtype="string"),
        }
    )

    result = loader.load(frame, LoadRequest(table="people"))

    assert result.row_count == 0
    assert result.batch_count == 0
    assert database.sessions == 0


def test_empty_truncate_insert_clears_the_table() -> None:
    loader, database = _loader()
    frame = pd.DataFrame(
        {
            "id": pd.Series([], dtype="Int64"),
            "name": pd.Series([], dtype="string"),
        }
    )

    result = loader.load(
        frame,
        LoadRequest(table="people", mode=LoadMode.TRUNCATE_INSERT),
    )

    assert result.row_count == 0
    assert result.batch_count == 0
    assert database.calls == [("execute", 'TRUNCATE TABLE "public"."people"', ())]


def test_values_are_converted_for_the_database() -> None:
    loader, database = _loader()
    frame = pd.DataFrame(
        {
            "id": pd.Series([1, pd.NA], dtype="Int64"),
            "score": pd.Series([float("nan"), 2.5], dtype="Float64"),
            "when": [pd.Timestamp("2026-01-02"), pd.NaT],
        }
    )

    loader.load(frame, LoadRequest(table="people", batch_size=2))

    rows = cast(list[tuple[object, ...]], database.calls[0][2])
    assert rows == [
        (1, None, datetime(2026, 1, 2)),
        (None, 2.5, None),
    ]


def test_identifiers_are_validated_and_quoted() -> None:
    loader, database = _loader()
    frame = pd.DataFrame({"select": [1]})

    loader.load(frame, LoadRequest(table="from"))

    sql = database.calls[0][1]
    assert '"public"."from"' in sql
    assert '"select"' in sql


def test_invalid_table_identifier_is_rejected() -> None:
    loader, _ = _loader()
    frame = pd.DataFrame({"id": [1]})

    with pytest.raises(LoadError) as caught:
        loader.load(
            frame,
            LoadRequest(table="people; DROP TABLE people"),
        )

    assert caught.value.code == "LOAD_INVALID_IDENTIFIER"
    assert caught.value.context == {"field": "table"}


def test_invalid_column_identifier_and_duplicates_are_rejected() -> None:
    loader, _ = _loader()

    with pytest.raises(LoadError) as invalid:
        loader.load(
            pd.DataFrame({"bad-name": [1]}),
            LoadRequest(table="people"),
        )
    with pytest.raises(LoadError) as duplicate:
        loader.load(
            pd.DataFrame([[1, 2]], columns=["id", "id"]),
            LoadRequest(table="people"),
        )

    assert invalid.value.code == "LOAD_INVALID_IDENTIFIER"
    assert invalid.value.context == {"field": "column", "column_index": 0}
    assert duplicate.value.code == "LOAD_INVALID_COLUMNS"
    assert duplicate.value.context == {"column": "id"}


def test_missing_conflict_column_is_rejected() -> None:
    loader, _ = _loader()
    frame = pd.DataFrame({"id": [1], "name": ["Ada"]})

    with pytest.raises(LoadError) as caught:
        loader.load(
            frame,
            LoadRequest(
                table="people",
                mode=LoadMode.UPSERT,
                conflict_columns=("missing",),
            ),
        )

    assert caught.value.code == "LOAD_INVALID_CONFLICT_COLUMNS"
    assert caught.value.context == {"columns": ["missing"]}


def test_load_request_validation() -> None:
    with pytest.raises(ValueError, match="table"):
        LoadRequest(table=" ")
    with pytest.raises(ValueError, match="batch_size"):
        LoadRequest(table="people", batch_size=0)
    with pytest.raises(ValueError, match="batch_size"):
        LoadRequest(table="people", batch_size=10_001)
    with pytest.raises(ValueError, match="conflict column"):
        LoadRequest(table="people", mode=LoadMode.UPSERT)
    with pytest.raises(ValueError, match="only valid for upsert"):
        LoadRequest(table="people", conflict_columns=("id",))
    with pytest.raises(ValueError, match="unique"):
        LoadRequest(
            table="people",
            mode=LoadMode.UPSERT,
            conflict_columns=("id", "id"),
        )
