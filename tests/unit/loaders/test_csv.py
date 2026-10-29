"""Unit tests for CSV loaders."""

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from domain.errors import LoadError, SandboxError
from infrastructure.loaders.csv import save_csv


def _raise_sandbox(*args: object, **kwargs: object) -> None:
    raise SandboxError(
        code="SANDBOX_PATH_DENIED",
        message="denied",
        module="test",
    )


def test_save_csv_writes_and_returns_a_copy(tmp_path: Path) -> None:
    frame = pd.DataFrame({"name": ["Ada"]})
    path = tmp_path / "output.csv"

    result = save_csv(frame, path=str(path))
    result.loc[0, "name"] = "Grace"

    assert path.read_text(encoding="utf-8").strip() == "name\nAda"
    assert frame.loc[0, "name"] == "Ada"


def test_save_csv_wraps_failures_without_leaking_os_details(tmp_path: Path) -> None:
    frame = pd.DataFrame({"name": ["Ada"]})

    with pytest.raises(LoadError) as caught:
        save_csv(frame, path=str(tmp_path))

    assert caught.value.code == "LOAD_FAILED"
    assert caught.value.message == "CSV load failed"
    assert caught.value.context == {"path": str(tmp_path)}


def test_save_csv_failure_preserves_the_existing_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "output.csv"
    target.write_text("old", encoding="utf-8")

    def fail_after_partial_write(
        self: pd.DataFrame,
        handle: Any,
        **kwargs: object,
    ) -> None:
        del self, kwargs
        handle.write("partial")
        raise RuntimeError("boom")

    monkeypatch.setattr(pd.DataFrame, "to_csv", fail_after_partial_write)

    with pytest.raises(LoadError):
        save_csv(pd.DataFrame({"name": ["Ada"]}), path=str(target))

    assert target.read_text(encoding="utf-8") == "old"
    assert list(tmp_path.glob(".*.tmp")) == []


def test_save_csv_preserves_sandbox_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pd.DataFrame, "to_csv", _raise_sandbox)

    with pytest.raises(SandboxError, match="denied"):
        save_csv(pd.DataFrame({"name": ["Ada"]}), path="output.csv")
