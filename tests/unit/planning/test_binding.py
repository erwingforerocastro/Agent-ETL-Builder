"""Unit tests for deterministic source and destination binding."""

import pytest

from application.planning.binding import (
    destination_operation_for_path,
    same_workspace_path,
    source_operation_for_path,
)


@pytest.mark.parametrize(
    ("path", "operation"),
    [
        ("input.csv", "read_csv"),
        ("INPUT.CSV", "read_csv"),
        ("dir\\input.json", "read_json"),
        ("input.jsonl", "read_jsonl"),
        ("input.ndjson", "read_jsonl"),
        ("input.parquet", "read_parquet"),
        ("input.pq", "read_parquet"),
        ("input.txt", None),
        (None, None),
        ("", None),
    ],
)
def test_source_operation_for_path(path: str | None, operation: str | None) -> None:
    assert source_operation_for_path(path) == operation


@pytest.mark.parametrize(
    ("path", "operation"),
    [
        ("output.csv", "save_csv"),
        ("OUTPUT.JSON", "save_json"),
        ("dir\\output.jsonl", "save_jsonl"),
        ("output.ndjson", "save_jsonl"),
        ("output.parquet", "save_parquet"),
        ("output.pq", "save_parquet"),
        ("output.txt", None),
        (None, None),
    ],
)
def test_destination_operation_for_path(path: str | None, operation: str | None) -> None:
    assert destination_operation_for_path(path) == operation


@pytest.mark.parametrize(
    ("source", "destination", "expected"),
    [
        ("input.csv", "input.csv", True),
        (".\\input.csv", "input.csv", True),
        ("dir\\input.csv", "dir/input.csv", True),
        ("DIR/input.csv", "dir/INPUT.csv", True),
        ("input.csv", "output.csv", False),
        (None, "output.csv", False),
        ("input.csv", None, False),
    ],
)
def test_same_workspace_path(
    source: str | None,
    destination: str | None,
    expected: bool,
) -> None:
    assert same_workspace_path(source, destination) is expected
