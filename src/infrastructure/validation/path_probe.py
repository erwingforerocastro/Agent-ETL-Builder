"""Filesystem-backed workspace path inspection."""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from application.ports.workspace import WorkspacePathError, WorkspacePathInfo


class FilesystemWorkspaceProbe:
    """Resolves and inspects paths relative to a fixed workspace root."""

    def __init__(self, workspace_root: Path | str) -> None:
        self._root = Path(workspace_root).resolve(strict=False)

    def inspect(self, parts: Sequence[str]) -> WorkspacePathInfo:
        candidate = self._root.joinpath(*parts)
        try:
            resolved = candidate.resolve(strict=False)
        except OSError:
            return WorkspacePathInfo(
                resolved="",
                error=WorkspacePathError.RESOLVE_FAILED,
            )

        try:
            common = os.path.commonpath([str(self._root), str(resolved)])
        except ValueError:
            return WorkspacePathInfo(
                resolved=str(resolved),
                error=WorkspacePathError.OUTSIDE_WORKSPACE,
            )
        if os.path.normcase(common) != os.path.normcase(str(self._root)):
            return WorkspacePathInfo(
                resolved=str(resolved),
                error=WorkspacePathError.OUTSIDE_WORKSPACE,
            )

        current = self._root
        for part in parts:
            current = current / part
            try:
                if current.is_symlink():
                    return WorkspacePathInfo(resolved=str(resolved), symlink=True)
                if not current.exists():
                    break
            except OSError:
                return WorkspacePathInfo(
                    resolved=str(resolved),
                    error=WorkspacePathError.INSPECT_FAILED,
                )

        return WorkspacePathInfo(resolved=str(resolved))


__all__ = ["FilesystemWorkspaceProbe"]
