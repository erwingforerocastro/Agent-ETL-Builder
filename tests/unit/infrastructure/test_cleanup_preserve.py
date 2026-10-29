"""Unit tests for preserving monitoring logs during cleanup."""

from pathlib import Path

import pytest

from domain.entities.run import CleanupPolicy
from infrastructure.cleanup.filesystem import FilesystemCleanup


def test_cleanup_preserves_transform_log_and_removes_partial_artifacts(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    transform_log = run_dir / "transform_log.csv"
    transform_log.write_text("ID\nrun-1\n", encoding="utf-8")
    partial = run_dir / "partial.csv"
    partial.write_text("partial", encoding="utf-8")
    cleanup = FilesystemCleanup(tmp_path)

    result = cleanup.apply("run-1", CleanupPolicy.CLEANUP)

    assert result.retained == (str(transform_log),)
    assert result.removed == (str(partial),)
    assert transform_log.exists()
    assert not partial.exists()
    assert run_dir.exists()


def test_cleanup_keeps_a_directory_with_only_the_transform_log(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    transform_log = run_dir / "transform_log.csv"
    transform_log.write_text("ID\nrun-1\n", encoding="utf-8")
    cleanup = FilesystemCleanup(tmp_path)

    result = cleanup.apply("run-1", CleanupPolicy.CLEANUP)

    assert result.retained == (str(transform_log),)
    assert result.removed == ()
    assert transform_log.exists()


def test_cleanup_removes_a_directory_without_a_transform_log(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    (run_dir / "partial.csv").write_text("partial", encoding="utf-8")
    cleanup = FilesystemCleanup(tmp_path)

    result = cleanup.apply("run-1", CleanupPolicy.CLEANUP)

    assert result.removed == (str(run_dir),)
    assert not run_dir.exists()


def test_cleanup_preserves_a_custom_file_name(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    keep = run_dir / "keep.log"
    keep.write_text("keep", encoding="utf-8")
    cleanup = FilesystemCleanup(tmp_path, preserve=("keep.log",))

    result = cleanup.apply("run-1", CleanupPolicy.CLEANUP)

    assert result.retained == (str(keep),)
    assert keep.exists()


def test_cleanup_rejects_unsafe_preserve_names(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="simple file names"):
        FilesystemCleanup(tmp_path, preserve=("../escape.log",))
