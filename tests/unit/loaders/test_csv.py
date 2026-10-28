"""Unit tests for CSV loaders."""

from pathlib import Path

import pandas as pd
import pytest

from domain.errors import LoadError
from infrastructure.loaders.csv import save_csv


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
