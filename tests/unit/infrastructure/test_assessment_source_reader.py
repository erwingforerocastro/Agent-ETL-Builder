"""Unit tests for workspace-confined assessment source access."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pandas as pd
import pytest

from domain.errors import IngestionError
from infrastructure.assessment.source_reader import WorkspaceSourceReader
from infrastructure.validation.path_probe import FilesystemWorkspaceProbe


def _reader(workspace: Path) -> WorkspaceSourceReader:
    return WorkspaceSourceReader(FilesystemWorkspaceProbe(workspace))


def test_describes_csv_and_streams_chunks(tmp_path: Path) -> None:
    (tmp_path / "input.csv").write_text("id,name\n1,Ada\n2,Bob\n3,Cyd\n", encoding="utf-8")
    reader = _reader(tmp_path)

    source = reader.describe("input.csv")
    chunks = [cast(pd.DataFrame, chunk) for chunk in reader.iter_chunks(source, chunk_size=2)]

    assert source.source_type == "csv"
    assert source.operation == "read_csv"
    assert source.source_id.startswith("src_")
    assert source.params == {"path": "input.csv"}
    assert source.content_hash.startswith("sha256:")
    assert [len(chunk) for chunk in chunks] == [2, 1]


@pytest.mark.parametrize(
    ("name", "content", "source_type", "operation"),
    [
        ("input.json", '[{"id": 1}, {"id": 2}]', "json", "read_json"),
        ("input.jsonl", '{"id": 1}\n{"id": 2}\n', "jsonl", "read_jsonl"),
    ],
)
def test_describes_json_variants(
    tmp_path: Path,
    name: str,
    content: str,
    source_type: str,
    operation: str,
) -> None:
    (tmp_path / name).write_text(content, encoding="utf-8")
    reader = _reader(tmp_path)

    source = reader.describe(name)

    assert source.source_type == source_type
    assert source.operation == operation
    assert len(list(reader.iter_chunks(source, chunk_size=10))) == 1


def test_describes_and_streams_parquet(tmp_path: Path) -> None:
    frame = pd.DataFrame({"id": [1, 2, 3]})
    frame.to_parquet(tmp_path / "input.parquet", index=False)
    reader = _reader(tmp_path)

    source = reader.describe("input.parquet")
    chunks = [cast(pd.DataFrame, chunk) for chunk in reader.iter_chunks(source, chunk_size=2)]

    assert source.source_type == "parquet"
    assert source.operation == "read_parquet"
    assert sum(len(chunk) for chunk in chunks) == 3


def test_source_ids_are_stable_for_the_same_file(tmp_path: Path) -> None:
    (tmp_path / "input.csv").write_text("id\n1\n", encoding="utf-8")
    reader = _reader(tmp_path)

    first = reader.describe("input.csv")
    second = reader.describe("./input.csv")

    assert first.source_id == second.source_id
    assert first.content_hash == second.content_hash


@pytest.mark.parametrize(
    ("reference", "code"),
    [
        ("", "SOURCE_REFERENCE_INVALID"),
        (" ", "SOURCE_REFERENCE_INVALID"),
        ("../outside.csv", "SOURCE_REFERENCE_INVALID"),
        ("C:/absolute.csv", "SOURCE_REFERENCE_INVALID"),
        ("/absolute.csv", "SOURCE_REFERENCE_INVALID"),
        ("missing.csv", "SOURCE_NOT_FOUND"),
        ("folder", "SOURCE_NOT_FILE"),
        ("input.txt", "SOURCE_UNSUPPORTED_TYPE"),
    ],
)
def test_rejects_unsafe_missing_or_unsupported_sources(
    tmp_path: Path,
    reference: str,
    code: str,
) -> None:
    (tmp_path / "input.txt").write_text("data", encoding="utf-8")
    (tmp_path / "folder").mkdir()

    with pytest.raises(IngestionError) as caught:
        _reader(tmp_path).describe(reference)

    assert caught.value.code == code


def test_iter_chunks_rejects_invalid_size(tmp_path: Path) -> None:
    (tmp_path / "input.csv").write_text("id\n1\n", encoding="utf-8")
    reader = _reader(tmp_path)
    source = reader.describe("input.csv")

    with pytest.raises(ValueError, match="chunk_size"):
        list(reader.iter_chunks(source, chunk_size=0))
