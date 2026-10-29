"""Transactional PostgreSQL table loading."""

from __future__ import annotations

import math
from collections.abc import Iterator

import pandas as pd
from psycopg import sql

from application.loaders.models import LoadMode, LoadRequest, LoadResult
from application.ports.database import DatabasePort
from domain.errors import LoadError
from infrastructure.database.identifiers import validate_identifier


def _load_error(
    code: str,
    message: str,
    context: dict[str, object] | None = None,
) -> LoadError:
    return LoadError(
        code=code,
        message=message,
        module=__name__,
        context=context,
    )


def _identifier(value: str, field_name: str) -> str:
    try:
        return validate_identifier(value, field_name)
    except ValueError as exc:
        raise _load_error(
            "LOAD_INVALID_IDENTIFIER",
            "Database identifier is invalid",
            {"field": field_name},
        ) from exc


def _frame_columns(df: pd.DataFrame) -> tuple[str, ...]:
    if df.columns.empty:
        raise _load_error(
            "LOAD_INVALID_COLUMNS",
            "DataFrame must have at least one column",
            {"reason": "no_columns"},
        )
    names: list[str] = []
    seen: set[str] = set()
    for index, column in enumerate(df.columns):
        if not isinstance(column, str):
            raise _load_error(
                "LOAD_INVALID_COLUMNS",
                "DataFrame column names must be strings",
                {"column_index": index},
            )
        try:
            name = validate_identifier(column, "column")
        except ValueError as exc:
            raise _load_error(
                "LOAD_INVALID_IDENTIFIER",
                "Database column identifier is invalid",
                {"field": "column", "column_index": index},
            ) from exc
        if name in seen:
            raise _load_error(
                "LOAD_INVALID_COLUMNS",
                "DataFrame column names must be unique",
                {"column": name},
            )
        seen.add(name)
        names.append(name)
    return tuple(names)


def _conflict_columns(request: LoadRequest, columns: tuple[str, ...]) -> tuple[str, ...]:
    if not request.conflict_columns:
        return ()
    resolved: list[str] = []
    for column in request.conflict_columns:
        try:
            resolved.append(validate_identifier(column, "conflict column"))
        except ValueError as exc:
            raise _load_error(
                "LOAD_INVALID_IDENTIFIER",
                "Conflict column identifier is invalid",
                {"field": "conflict_column"},
            ) from exc
    if len(set(resolved)) != len(resolved):
        raise _load_error(
            "LOAD_INVALID_CONFLICT_COLUMNS",
            "Conflict columns must be unique",
            {"reason": "duplicate"},
        )
    missing = [column for column in resolved if column not in columns]
    if missing:
        raise _load_error(
            "LOAD_INVALID_CONFLICT_COLUMNS",
            "Conflict columns must exist in the DataFrame",
            {"columns": missing},
        )
    return tuple(resolved)


def _build_insert_sql(
    *,
    schema: str,
    table: str,
    columns: tuple[str, ...],
    mode: LoadMode,
    conflict_columns: tuple[str, ...],
) -> str:
    table_sql = sql.Identifier(schema, table)
    columns_sql = sql.SQL(", ").join(sql.Identifier(column) for column in columns)
    placeholders = sql.SQL(", ").join(sql.Placeholder() for _ in columns)
    statement = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
        table_sql,
        columns_sql,
        placeholders,
    )
    if mode is LoadMode.UPSERT:
        conflict_sql = sql.SQL(", ").join(sql.Identifier(column) for column in conflict_columns)
        conflict_set = set(conflict_columns)
        update_columns = tuple(column for column in columns if column not in conflict_set)
        if update_columns:
            updates = sql.SQL(", ").join(
                sql.SQL("{} = EXCLUDED.{}").format(
                    sql.Identifier(column),
                    sql.Identifier(column),
                )
                for column in update_columns
            )
            statement = sql.SQL("{} ON CONFLICT ({}) DO UPDATE SET {}").format(
                statement,
                conflict_sql,
                updates,
            )
        else:
            statement = sql.SQL("{} ON CONFLICT ({}) DO NOTHING").format(
                statement,
                conflict_sql,
            )
    return statement.as_string(None)


def _truncate_sql(*, schema: str, table: str) -> str:
    return sql.SQL("TRUNCATE TABLE {}").format(sql.Identifier(schema, table)).as_string(None)


def _database_value(value: object) -> object:
    if value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    item = getattr(value, "item", None)
    if callable(item) and not isinstance(value, str | bytes):
        try:
            return item()
        except (AttributeError, ValueError):
            return value
    return value


def _rows(df: pd.DataFrame) -> Iterator[tuple[object, ...]]:
    for row in df.itertuples(index=False, name=None):
        yield tuple(_database_value(value) for value in row)


def _batches(
    rows: Iterator[tuple[object, ...]],
    batch_size: int,
) -> Iterator[list[tuple[object, ...]]]:
    batch: list[tuple[object, ...]] = []
    for row in rows:
        batch.append(row)
        if len(batch) == batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


class PostgresTableLoader:
    """Loads DataFrames into existing PostgreSQL tables transactionally."""

    def __init__(self, database: DatabasePort) -> None:
        self._database = database

    def load(self, df: pd.DataFrame, request: LoadRequest) -> LoadResult:
        """Load ``df`` using insert, upsert, or truncate-insert semantics."""
        schema = _identifier(request.schema, "schema")
        table = _identifier(request.table, "table")
        columns = _frame_columns(df)
        conflict_columns = _conflict_columns(request, columns)
        insert_sql = _build_insert_sql(
            schema=schema,
            table=table,
            columns=columns,
            mode=request.mode,
            conflict_columns=conflict_columns,
        )
        row_count = len(df)
        batch_count = 0
        if row_count == 0 and request.mode is not LoadMode.TRUNCATE_INSERT:
            return LoadResult(
                schema=schema,
                table=table,
                mode=request.mode,
                row_count=0,
                batch_count=0,
            )

        with self._database.connect() as session:
            if request.mode is LoadMode.TRUNCATE_INSERT:
                session.execute(_truncate_sql(schema=schema, table=table))
            for batch in _batches(_rows(df), request.batch_size):
                session.execute_many(insert_sql, batch)
                batch_count += 1

        return LoadResult(
            schema=schema,
            table=table,
            mode=request.mode,
            row_count=row_count,
            batch_count=batch_count,
        )


__all__ = ["PostgresTableLoader"]
