"""Atomic file replacement helpers for file loaders."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import BinaryIO, TextIO, cast


@contextmanager
def _atomic_open(
    path: str | Path,
    *,
    mode: str,
    encoding: str = "utf-8",
    newline: str | None = "",
) -> Iterator[object]:
    target = Path(path)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    try:
        try:
            if "b" in mode:
                handle = os.fdopen(descriptor, mode)
            else:
                handle = os.fdopen(descriptor, mode, encoding=encoding, newline=newline)
        except BaseException:
            os.close(descriptor)
            raise
        with handle:
            yield handle
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except BaseException:
        with suppress(OSError):
            os.unlink(temporary)
        raise


@contextmanager
def atomic_text(
    path: str | Path,
    *,
    encoding: str = "utf-8",
    newline: str | None = "",
) -> Iterator[TextIO]:
    """Yield a text handle that replaces ``path`` only after a clean close."""
    with _atomic_open(path, mode="w", encoding=encoding, newline=newline) as handle:
        yield cast(TextIO, handle)


@contextmanager
def atomic_binary(path: str | Path) -> Iterator[BinaryIO]:
    """Yield a binary handle that replaces ``path`` only after a clean close."""
    with _atomic_open(path, mode="wb") as handle:
        yield cast(BinaryIO, handle)


__all__ = ["atomic_binary", "atomic_text"]
