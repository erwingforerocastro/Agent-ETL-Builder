"""Unit tests for the Parquet loader."""

from pathlib import Path

import pandas as pd
import pytest

from domain.errors import LoadError
from infrastructure.loaders.parquet import save_parquet


def test_save_parquet_round_trips(tmp_path: Path) -> None:
    frame = pd.DataFrame({"name": ["Ada", "Café"], "score": [1, 2]})
    path = tmp_path / "output.parquet"

    result = save_parquet(frame, path=str(path))

    loaded = pd.read_parquet(path)
    assert loaded["name"].tolist() == ["Ada", "Café"]
    assert loaded["score"].tolist() == [1, 2]
    assert result is not frame
    assert result.equals(frame)


def test_save_parquet_wraps_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fail)

    with pytest.raises(LoadError) as caught:
        save_parquet(pd.DataFrame({"name": ["Ada"]}), path=str(tmp_path / "output.parquet"))

    assert caught.value.code == "LOAD_FAILED"
    assert caught.value.message == "Parquet load failed"
    assert caught.value.context == {"path": str(tmp_path / "output.parquet")}
