"""Workspace filesystem inspection contract used by plan validation."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class WorkspacePathError(Enum):
    """A filesystem inspection that could not be completed."""

    RESOLVE_FAILED = "resolve_failed"
    OUTSIDE_WORKSPACE = "outside_workspace"
    INSPECT_FAILED = "inspect_failed"


@dataclass(frozen=True, slots=True)
class WorkspacePathInfo:
    """Result of inspecting a workspace-relative path."""

    resolved: str
    symlink: bool = False
    error: WorkspacePathError | None = None


class WorkspaceProbePort(Protocol):
    """Inspects paths without exposing filesystem details to the application."""

    def inspect(self, parts: Sequence[str]) -> WorkspacePathInfo: ...
