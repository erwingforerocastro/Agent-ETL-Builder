"""Unit tests for atomic file replacement."""

from pathlib import Path

import pytest

from infrastructure.loaders.atomic import atomic_binary, atomic_text


def test_atomic_text_replaces_an_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "output.txt"
    target.write_text("old", encoding="utf-8")

    with atomic_text(target) as handle:
        handle.write("new")

    assert target.read_text(encoding="utf-8") == "new"
    assert list(tmp_path.glob(".*.tmp")) == []


def _fail_after_partial_write(target: Path) -> None:
    with atomic_text(target) as handle:
        handle.write("partial")
        raise RuntimeError("boom")


def _write_text(target: Path, text: str) -> None:
    with atomic_text(target) as handle:
        handle.write(text)


def test_atomic_text_preserves_the_original_on_failure(tmp_path: Path) -> None:
    target = tmp_path / "output.txt"
    target.write_text("old", encoding="utf-8")

    with pytest.raises(RuntimeError, match="boom"):
        _fail_after_partial_write(target)

    assert target.read_text(encoding="utf-8") == "old"
    assert list(tmp_path.glob(".*.tmp")) == []


def test_atomic_binary_writes_bytes(tmp_path: Path) -> None:
    target = tmp_path / "output.bin"

    with atomic_binary(target) as handle:
        handle.write(b"data")

    assert target.read_bytes() == b"data"
    assert list(tmp_path.glob(".*.tmp")) == []


def test_atomic_text_requires_an_existing_parent(tmp_path: Path) -> None:
    target = tmp_path / "missing" / "output.txt"

    with pytest.raises(FileNotFoundError):
        _write_text(target, "data")
