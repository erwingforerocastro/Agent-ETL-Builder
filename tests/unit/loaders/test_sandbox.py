"""Sandboxed file-loader smoke tests."""

from collections.abc import Callable
from pathlib import Path

import pandas as pd
import pytest

from infrastructure.loaders.csv import save_csv
from infrastructure.loaders.json import save_json, save_jsonl
from infrastructure.loaders.parquet import save_parquet
from infrastructure.sandbox.executor import SandboxExecutor
from infrastructure.sandbox.limits import SandboxLimits

Loader = Callable[..., pd.DataFrame]


@pytest.mark.parametrize(
    ("loader", "filename"),
    [
        (save_csv, "output.csv"),
        (save_json, "output.json"),
        (save_jsonl, "output.jsonl"),
        (save_parquet, "output.parquet"),
    ],
)
def test_file_loader_works_under_the_sandbox(
    tmp_path: Path,
    loader: Loader,
    filename: str,
) -> None:
    sandbox = SandboxExecutor(
        SandboxLimits(timeout_seconds=10, memory_mb=512),
        workspace=tmp_path,
    )

    sandbox.run(loader, pd.DataFrame({"name": ["Ada"]}), path=filename)

    assert (tmp_path / filename).exists()
