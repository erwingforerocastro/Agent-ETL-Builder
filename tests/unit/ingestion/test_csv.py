"""Unit tests for CSV ingestion."""

from pathlib import Path

import pandas as pd
import pytest

from domain.errors import IngestionError
from infrastructure.ingestion.csv import read_csv


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


def test_read_csv_wraps_failures_without_leaking_os_details(tmp_path: Path) -> None:
    path = tmp_path / "missing.csv"

    with pytest.raises(IngestionError) as caught:
        read_csv(path=str(path))

    assert caught.value.code == "INGESTION_FAILED"
    assert caught.value.message == "CSV ingestion failed"
    assert caught.value.context == {"path": str(path)}
