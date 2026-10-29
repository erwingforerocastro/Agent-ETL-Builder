"""Unit tests for JSON and JSON Lines loaders."""

from pathlib import Path

import pandas as pd
import pytest

from domain.errors import LoadError
from infrastructure.loaders.json import save_json, save_jsonl


def test_save_json_round_trips_records(tmp_path: Path) -> None:
    frame = pd.DataFrame({"name": ["Ada", "Café"], "score": [1, 2]})
    path = tmp_path / "output.json"

    result = save_json(frame, path=str(path))

    loaded = pd.read_json(path, orient="records")
    assert loaded["name"].tolist() == ["Ada", "Café"]
    assert loaded["score"].tolist() == [1, 2]
    assert result is not frame
    assert result.equals(frame)


def test_save_jsonl_round_trips_records(tmp_path: Path) -> None:
    frame = pd.DataFrame({"name": ["Ada", "Café"], "score": [1, 2]})
    path = tmp_path / "output.jsonl"

    save_jsonl(frame, path=str(path))

    loaded = pd.read_json(path, lines=True)
    assert loaded["name"].tolist() == ["Ada", "Café"]
    assert loaded["score"].tolist() == [1, 2]


def test_save_json_wraps_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(pd.DataFrame, "to_json", fail)

    with pytest.raises(LoadError) as caught:
        save_json(pd.DataFrame({"name": ["Ada"]}), path=str(tmp_path / "output.json"))

    assert caught.value.code == "LOAD_FAILED"
    assert caught.value.message == "JSON load failed"
    assert caught.value.context == {"path": str(tmp_path / "output.json")}
