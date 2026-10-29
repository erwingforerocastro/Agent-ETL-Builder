"""Atomic JSON and JSON Lines loaders."""

import pandas as pd

from domain.errors import LoadError, SandboxError
from infrastructure.loaders.atomic import atomic_text


def save_json(df: pd.DataFrame, *, path: str = "output.json") -> pd.DataFrame:
    try:
        with atomic_text(path, newline="") as handle:
            df.to_json(
                handle,
                orient="records",
                date_format="iso",
                force_ascii=False,
            )
        return df.copy()
    except SandboxError:
        raise
    except Exception as exc:
        raise LoadError(
            code="LOAD_FAILED",
            message="JSON load failed",
            module=__name__,
            context={"path": path},
        ) from exc


def save_jsonl(df: pd.DataFrame, *, path: str = "output.jsonl") -> pd.DataFrame:
    try:
        with atomic_text(path, newline="") as handle:
            df.to_json(
                handle,
                orient="records",
                lines=True,
                date_format="iso",
                force_ascii=False,
            )
        return df.copy()
    except SandboxError:
        raise
    except Exception as exc:
        raise LoadError(
            code="LOAD_FAILED",
            message="JSON Lines load failed",
            module=__name__,
            context={"path": path},
        ) from exc


__all__ = ["save_json", "save_jsonl"]
