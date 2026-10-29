"""Unit tests for JSON and JSONL ingestion."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pandas as pd
import pytest

from domain.errors import IngestionError, SandboxError
from infrastructure.ingestion.json import (
    iter_json_chunks,
    iter_jsonl_chunks,
    read_json,
    read_jsonl,
)


def _raise_sandbox(*args: object, **kwargs: object) -> None:
    raise SandboxError(
        code="SANDBOX_PATH_DENIED",
        message="denied",
        module="test",
    )


def test_read_json_reads_a_json_array(tmp_path: Path) -> None:
    path = tmp_path / "input.json"
    path.write_text(
        '[{"id": 1, "name": "Ada"}, {"id": 2, "name": "Bob"}]',
        encoding="utf-8",
    )

    result = read_json(path=str(path))

    assert result.to_dict("records") == [
        {"id": 1, "name": "Ada"},
        {"id": 2, "name": "Bob"},
    ]


def test_read_json_returns_empty_frame_for_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.json"
    path.write_text("", encoding="utf-8")

    assert read_json(path=str(path)).empty


def test_read_json_treats_empty_parser_errors_as_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "empty.json"
    path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(
        "infrastructure.ingestion.json._is_empty_file",
        lambda _path: False,
    )

    def raise_empty(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise pd.errors.EmptyDataError("empty")

    monkeypatch.setattr(pd, "read_json", raise_empty)

    assert read_json(path=str(path)).empty


def test_read_json_wraps_missing_files(tmp_path: Path) -> None:
    with pytest.raises(IngestionError) as caught:
        read_json(path=str(tmp_path / "missing.json"))

    assert caught.value.code == "INGESTION_FAILED"
    assert caught.value.message == "JSON ingestion failed"
    assert caught.value.context == {"path": str(tmp_path / "missing.json")}


def test_read_json_wraps_malformed_documents(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text('{"id": 1}', encoding="utf-8")

    with pytest.raises(IngestionError, match="JSON ingestion failed"):
        read_json(path=str(path))


def test_read_json_preserves_sandbox_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "input.json"
    path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(pd, "read_json", _raise_sandbox)

    with pytest.raises(SandboxError, match="denied"):
        read_json(path=str(path))


def test_read_json_preserves_sandbox_errors_from_empty_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_open(self: Path, mode: str = "r", *args: object, **kwargs: object) -> None:
        del self, mode, args, kwargs
        raise SandboxError(
            code="SANDBOX_PATH_DENIED",
            message="denied",
            module="test",
        )

    monkeypatch.setattr(Path, "open", fail_open)

    with pytest.raises(SandboxError, match="denied"):
        read_json(path="input.json")


def test_read_jsonl_reads_lines(tmp_path: Path) -> None:
    path = tmp_path / "input.jsonl"
    path.write_text(
        '{"id": 1, "name": "Ada"}\n{"id": 2, "name": "Bob"}\n',
        encoding="utf-8",
    )

    result = read_jsonl(path=str(path))

    assert result["id"].tolist() == [1, 2]


def test_read_jsonl_returns_empty_frame_for_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")

    assert read_jsonl(path=str(path)).empty


def test_read_jsonl_wraps_missing_files(tmp_path: Path) -> None:
    with pytest.raises(IngestionError) as caught:
        read_jsonl(path=str(tmp_path / "missing.jsonl"))

    assert caught.value.message == "JSONL ingestion failed"
    assert caught.value.context == {"path": str(tmp_path / "missing.jsonl")}


def test_read_jsonl_preserves_sandbox_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "input.jsonl"
    path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(pd, "read_json", _raise_sandbox)

    with pytest.raises(SandboxError, match="denied"):
        read_jsonl(path=str(path))


def test_iter_json_chunks_uses_deterministic_chunks(tmp_path: Path) -> None:
    path = tmp_path / "input.json"
    path.write_text(
        '[{"id": 1}, {"id": 2}, {"id": 3}]',
        encoding="utf-8",
    )

    chunks = list(iter_json_chunks(path=str(path), chunk_size=2))

    assert [chunk["id"].tolist() for chunk in chunks] == [[1, 2], [3]]


def test_iter_json_chunks_returns_nothing_for_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.json"
    path.write_text("", encoding="utf-8")

    assert list(iter_json_chunks(path=str(path), chunk_size=2)) == []


def test_iter_jsonl_chunks_streams_lines(tmp_path: Path) -> None:
    path = tmp_path / "input.jsonl"
    path.write_text(
        '{"id": 1}\n{"id": 2}\n{"id": 3}\n',
        encoding="utf-8",
    )

    chunks = list(iter_jsonl_chunks(path=str(path), chunk_size=2))

    assert [chunk["id"].tolist() for chunk in chunks] == [[1, 2], [3]]


def test_iter_jsonl_chunks_returns_nothing_for_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")

    assert list(iter_jsonl_chunks(path=str(path), chunk_size=2)) == []


def test_iter_jsonl_chunks_wraps_failures(tmp_path: Path) -> None:
    with pytest.raises(IngestionError, match="JSONL ingestion failed"):
        list(iter_jsonl_chunks(path=str(tmp_path / "missing.jsonl"), chunk_size=2))


@pytest.mark.parametrize("factory", [iter_json_chunks, iter_jsonl_chunks])
def test_chunked_json_rejects_invalid_chunk_size(
    factory: Callable[..., Iterator[pd.DataFrame]],
) -> None:
    with pytest.raises(ValueError, match="chunk_size"):
        list(factory(chunk_size=0))
