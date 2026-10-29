"""Filesystem cleanup for partial run artifacts."""

from __future__ import annotations

import shutil
from collections.abc import Sequence
from pathlib import Path

from application.ports.cleanup import CleanupResult
from domain.entities.run import CleanupPolicy

_DEFAULT_PRESERVE = ("transform_log.csv",)


class FilesystemCleanup:
    """Removes ``artifacts/<run_id>`` except explicitly preserved files."""

    def __init__(
        self,
        artifacts_root: Path,
        *,
        preserve: Sequence[str] = _DEFAULT_PRESERVE,
    ) -> None:
        self._root = artifacts_root.resolve()
        self._preserve = tuple(preserve)
        if any(
            not name or name in {".", ".."} or Path(name).name != name for name in self._preserve
        ):
            raise ValueError("preserve entries must be simple file names")

    def apply(self, run_id: str, policy: CleanupPolicy) -> CleanupResult:
        if not self._safe_run_id(run_id):
            return CleanupResult(
                policy=policy,
                errors=("invalid run_id for artifact cleanup",),
            )

        target = self._root / run_id
        if policy is CleanupPolicy.RETAIN:
            retained_targets = (str(target),) if target.exists() else ()
            return CleanupResult(policy=policy, retained=retained_targets)

        if not target.exists():
            return CleanupResult(policy=policy)

        try:
            target.resolve(strict=False).relative_to(self._root)
        except (OSError, ValueError) as exc:
            return CleanupResult(
                policy=policy,
                errors=(type(exc).__name__,),
            )

        if target.is_file():
            if target.name in self._preserve:
                return CleanupResult(policy=policy, retained=(str(target),))
            try:
                target.unlink()
            except OSError as exc:
                return CleanupResult(policy=policy, errors=(type(exc).__name__,))
            return CleanupResult(policy=policy, removed=(str(target),))

        if not target.is_dir():
            return CleanupResult(
                policy=policy,
                errors=("artifact target is not a file or directory",),
            )

        preserved = [target / name for name in self._preserve if (target / name).is_file()]
        if not preserved:
            try:
                shutil.rmtree(target)
            except OSError as exc:
                return CleanupResult(policy=policy, errors=(type(exc).__name__,))
            return CleanupResult(policy=policy, removed=(str(target),))

        removed: list[str] = []
        retained: list[str] = []
        errors: list[str] = []
        for child in target.iterdir():
            if child.name in self._preserve and child.is_file():
                retained.append(str(child))
                continue
            try:
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
                removed.append(str(child))
            except OSError as exc:
                errors.append(type(exc).__name__)
        return CleanupResult(
            policy=policy,
            removed=tuple(removed),
            retained=tuple(retained),
            errors=tuple(errors),
        )

    @staticmethod
    def _safe_run_id(run_id: str) -> bool:
        if run_id in {"", ".", ".."}:
            return False
        if "\x00" in run_id:
            return False
        return Path(run_id).name == run_id


__all__ = ["FilesystemCleanup"]
