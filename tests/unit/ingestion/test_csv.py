"""Unit tests for CSV ingestion."""

from pathlib import Path

import pandas as pd
import pytest

from domain.errors import IngestionError, SandboxError
from infrastructure.ingestion.csv import iter_csv_chunks, read_csv


def _raise_sandbox(*args: object, **kwargs: object) -> None:
    raise SandboxError(
        code="SANDBOX_PATH_DENIED",
        message="denied",
        module="test",
    )


def test_read_csv_returns_a_copy() -> None:
    frame = pd.DataFrame({"name": ["Ada"]})

    result = read_csv(df=frame)
    result.loc[0, "name"] = "Grace"

    assert frame.loc[0, "name"] == "Ada"


def test_read_csv_reads_a_file(tmp_path: Path) -> None:
    path = tmp_path / "input.csv"
    path.write_text("name\nAda\n", encoding="utf-8")

    result = read_csv(path=str(path))

    assert result["name"].tolist() == ["Ada"]


def test_read_csv_honors_encoding_delimiter_and_quotechar(tmp_path: Path) -> None:
    path = tmp_path / "input.tsv"
    path.write_text('name\tnote\nAda\t"hello, world"\n', encoding="utf-8-sig")

    result = read_csv(
        path=str(path),
        encoding="utf-8-sig",
        delimiter="\t",
        quotechar='"',
    )

    assert result.to_dict("records") == [{"name": "Ada", "note": "hello, world"}]


def test_read_csv_returns_empty_frame_for_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")

    assert read_csv(path=str(path)).empty


def test_read_csv_wraps_failures_without_leaking_os_details(tmp_path: Path) -> None:
    path = tmp_path / "missing.csv"

    with pytest.raises(IngestionError) as caught:
        read_csv(path=str(path))

    assert caught.value.code == "INGESTION_FAILED"
    assert caught.value.message == "CSV ingestion failed"
    assert caught.value.context == {"path": str(path)}


def test_read_csv_preserves_sandbox_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pd, "read_csv", _raise_sandbox)

    with pytest.raises(SandboxError, match="denied"):
        read_csv(path="input.csv")


def test_iter_csv_chunks_streams_rows(tmp_path: Path) -> None:
    path = tmp_path / "input.csv"
    path.write_text("id,name\n1,Ada\n2,Bob\n3,Cyd\n", encoding="utf-8")

    chunks = list(iter_csv_chunks(path=str(path), chunk_size=2))

    assert [chunk["id"].tolist() for chunk in chunks] == [[1, 2], [3]]


def test_iter_csv_chunks_returns_nothing_for_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")

    assert list(iter_csv_chunks(path=str(path), chunk_size=2)) == []


def test_iter_csv_chunks_wraps_failures(tmp_path: Path) -> None:
    with pytest.raises(IngestionError, match="CSV ingestion failed"):
        list(iter_csv_chunks(path=str(tmp_path / "missing.csv"), chunk_size=2))


def test_iter_csv_chunks_preserves_sandbox_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pd, "read_csv", _raise_sandbox)

    with pytest.raises(SandboxError, match="denied"):
        list(iter_csv_chunks(path="input.csv", chunk_size=2))


def test_iter_csv_chunks_rejects_invalid_chunk_size(tmp_path: Path) -> None:
    path = tmp_path / "input.csv"
    path.write_text("name\nAda\n", encoding="utf-8")

    with pytest.raises(ValueError, match="chunk_size"):
        list(iter_csv_chunks(path=str(path), chunk_size=0))
