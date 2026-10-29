"""Unit tests for Parquet ingestion."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from domain.errors import IngestionError, SandboxError
from infrastructure.ingestion.parquet import iter_parquet_chunks, read_parquet


def _raise_sandbox(*args: object, **kwargs: object) -> None:
    raise SandboxError(
        code="SANDBOX_PATH_DENIED",
        message="denied",
        module="test",
    )


def _write_parquet(path: Path) -> None:
    pd.DataFrame({"id": [1, 2, 3], "name": ["Ada", "Bob", "Cyd"]}).to_parquet(path, index=False)


def test_read_parquet_reads_a_file(tmp_path: Path) -> None:
    path = tmp_path / "input.parquet"
    _write_parquet(path)

    result = read_parquet(path=str(path))

    assert result.to_dict("records") == [
        {"id": 1, "name": "Ada"},
        {"id": 2, "name": "Bob"},
        {"id": 3, "name": "Cyd"},
    ]


def test_read_parquet_selects_columns(tmp_path: Path) -> None:
    path = tmp_path / "input.parquet"
    _write_parquet(path)

    result = read_parquet(path=str(path), columns=("name",))

    assert result.columns.tolist() == ["name"]


def test_read_parquet_reads_zero_row_files(tmp_path: Path) -> None:
    path = tmp_path / "empty.parquet"
    pd.DataFrame({"id": pd.Series([], dtype="int64")}).to_parquet(path, index=False)

    result = read_parquet(path=str(path))

    assert result.empty
    assert result.columns.tolist() == ["id"]


def test_read_parquet_wraps_missing_files(tmp_path: Path) -> None:
    with pytest.raises(IngestionError) as caught:
        read_parquet(path=str(tmp_path / "missing.parquet"))

    assert caught.value.code == "INGESTION_FAILED"
    assert caught.value.message == "Parquet ingestion failed"
    assert caught.value.context == {"path": str(tmp_path / "missing.parquet")}


def test_read_parquet_wraps_malformed_files(tmp_path: Path) -> None:
    path = tmp_path / "bad.parquet"
    path.write_text("not parquet", encoding="utf-8")

    with pytest.raises(IngestionError, match="Parquet ingestion failed"):
        read_parquet(path=str(path))


def test_read_parquet_preserves_sandbox_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "input.parquet"
    _write_parquet(path)
    monkeypatch.setattr(pd, "read_parquet", _raise_sandbox)

    with pytest.raises(SandboxError, match="denied"):
        read_parquet(path=str(path))


def test_iter_parquet_chunks_streams_batches(tmp_path: Path) -> None:
    path = tmp_path / "input.parquet"
    _write_parquet(path)

    chunks = list(iter_parquet_chunks(path=str(path), chunk_size=2))

    assert [chunk["id"].tolist() for chunk in chunks] == [[1, 2], [3]]


def test_iter_parquet_chunks_selects_columns(tmp_path: Path) -> None:
    path = tmp_path / "input.parquet"
    _write_parquet(path)

    chunks = list(iter_parquet_chunks(path=str(path), chunk_size=2, columns=("name",)))

    assert [chunk.columns.tolist() for chunk in chunks] == [["name"], ["name"]]


def test_iter_parquet_chunks_returns_nothing_for_zero_rows(tmp_path: Path) -> None:
    path = tmp_path / "empty.parquet"
    pd.DataFrame({"id": pd.Series([], dtype="int64")}).to_parquet(path, index=False)

    assert list(iter_parquet_chunks(path=str(path), chunk_size=2)) == []


def test_iter_parquet_chunks_rejects_invalid_chunk_size(tmp_path: Path) -> None:
    path = tmp_path / "input.parquet"
    _write_parquet(path)

    with pytest.raises(ValueError, match="chunk_size"):
        list(iter_parquet_chunks(path=str(path), chunk_size=0))


def test_iter_parquet_chunks_wraps_missing_files(tmp_path: Path) -> None:
    with pytest.raises(IngestionError, match="Parquet ingestion failed"):
        list(iter_parquet_chunks(path=str(tmp_path / "missing.parquet"), chunk_size=2))
