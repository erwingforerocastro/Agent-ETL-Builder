"""Filesystem cleanup for partial run artifacts."""

from __future__ import annotations

import shutil
from pathlib import Path

from application.ports.cleanup import CleanupResult
from domain.entities.run import CleanupPolicy


class FilesystemCleanup:
    """Removes ``artifacts/<run_id>`` when the configured policy allows it."""

    def __init__(self, artifacts_root: Path) -> None:
        self._root = artifacts_root.resolve()

    def apply(self, run_id: str, policy: CleanupPolicy) -> CleanupResult:
        if not self._safe_run_id(run_id):
            return CleanupResult(
                policy=policy,
                errors=("invalid run_id for artifact cleanup",),
            )

        target = self._root / run_id
        if policy is CleanupPolicy.RETAIN:
            retained = (str(target),) if target.exists() else ()
            return CleanupResult(policy=policy, retained=retained)

        if not target.exists():
            return CleanupResult(policy=policy)

        try:
            target.resolve(strict=False).relative_to(self._root)
        except (OSError, ValueError) as exc:
            return CleanupResult(
                policy=policy,
                errors=(type(exc).__name__,),
            )

        try:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        except OSError as exc:
            return CleanupResult(
                policy=policy,
                errors=(type(exc).__name__,),
            )
        return CleanupResult(policy=policy, removed=(str(target),))

    @staticmethod
    def _safe_run_id(run_id: str) -> bool:
        if run_id in {"", ".", ".."}:
            return False
        if "\x00" in run_id:
            return False
        return Path(run_id).name == run_id


__all__ = ["FilesystemCleanup"]
