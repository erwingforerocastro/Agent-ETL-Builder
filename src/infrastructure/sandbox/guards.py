"""Runtime access guards installed around one sandboxed step.

The guards are defense in depth for allowlisted Python callables. They are not
an OS-level sandbox; native extensions and code that bypasses the Python
globals they patch are outside their reach.
"""

from __future__ import annotations

import builtins
import io
import os
import socket
import sys
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any

from infrastructure.sandbox.errors import SandboxViolationError


def _path_from(value: object) -> Path | None:
    if isinstance(value, Path):
        return value
    if isinstance(value, str):
        return Path(value)
    if isinstance(value, bytes):
        return Path(os.fsdecode(value))
    fspath = getattr(value, "__fspath__", None)
    if callable(fspath):
        raw: object = fspath()
        if isinstance(raw, bytes):
            return Path(os.fsdecode(raw))
        if isinstance(raw, str):
            return Path(raw)
    return None


def _violation(*, code: str, message: str, operation: str) -> SandboxViolationError:
    return SandboxViolationError(
        code=code,
        message=message,
        context={"operation": operation},
    )


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _require_path(
    value: object,
    roots: tuple[Path, ...],
    operation: str,
    *,
    allow_missing: bool = False,
) -> None:
    path = _path_from(value)
    if path is None:
        return

    candidate = path if path.is_absolute() else Path.cwd() / path
    try:
        resolved = candidate.resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        raise _violation(
            code="SANDBOX_PATH_DENIED",
            message="File access is confined to the workspace",
            operation=operation,
        ) from exc
    if not resolved.exists() and allow_missing:
        return
    if not any(_is_within(resolved, root) for root in roots):
        raise _violation(
            code="SANDBOX_PATH_DENIED",
            message="File access is confined to the workspace",
            operation=operation,
        )


def _runtime_read_roots() -> tuple[Path, ...]:
    """Read-only roots required by the interpreter and its dependencies."""
    roots: set[Path] = set()
    for raw in (sys.prefix, sys.base_prefix):
        try:
            roots.add(Path(raw).resolve())
        except OSError:
            continue

    if os.name == "nt":
        system_root = os.environ.get("SYSTEMROOT")
        if system_root:
            with suppress(OSError):
                roots.add(Path(system_root).resolve())
    else:
        for raw in (
            "/dev/null",
            "/dev/random",
            "/dev/urandom",
            "/etc/localtime",
            "/etc/ssl",
            "/etc/timezone",
            "/lib",
            "/lib64",
            "/proc",
            "/sys",
            "/usr",
        ):
            try:
                roots.add(Path(raw).resolve())
            except OSError:
                continue
    return tuple(sorted(roots))


def _is_write_mode(mode: str) -> bool:
    return any(flag in mode for flag in "wax+")


def _install(
    originals: list[tuple[object, str, Any]],
    target: object,
    name: str,
    replacement: object,
) -> None:
    original = getattr(target, name)
    originals.append((target, name, original))
    setattr(target, name, replacement)


def _restore(originals: list[tuple[object, str, Any]]) -> None:
    for target, name, original in reversed(originals):
        setattr(target, name, original)


def _reject_dir_fd(operation: str) -> None:
    raise _violation(
        code="SANDBOX_PATH_DENIED",
        message="dir_fd is not supported in the sandbox",
        operation=operation,
    )


class _WorkspaceFilesystemGuard:
    """Confines file access while one sandboxed callable runs."""

    def __init__(self, workspace: Path) -> None:
        self._root = workspace.resolve()
        self._read_roots = (self._root, *_runtime_read_roots())
        self._original_open = builtins.open
        self._original_io_open = io.open
        self._original_os_open = os.open
        self._original_listdir = os.listdir
        self._original_scandir = os.scandir
        self._original_remove = os.remove
        self._original_unlink = os.unlink
        self._original_rmdir = os.rmdir
        self._original_mkdir = os.mkdir
        self._original_rename = os.rename
        self._original_replace = os.replace
        self._original_symlink = os.symlink
        self._original_link = os.link
        self._original_chmod = os.chmod
        self._original_utime = os.utime
        self._original_truncate = os.truncate
        self._original_chdir = os.chdir

    def install(self) -> list[tuple[object, str, Any]]:
        originals: list[tuple[object, str, Any]] = []
        _install(originals, builtins, "open", self.guarded_open)
        _install(originals, io, "open", self.guarded_io_open)
        _install(originals, os, "open", self.guarded_os_open)
        _install(originals, os, "listdir", self.guarded_listdir)
        _install(originals, os, "scandir", self.guarded_scandir)
        _install(originals, os, "remove", self.guarded_remove)
        _install(originals, os, "unlink", self.guarded_unlink)
        _install(originals, os, "rmdir", self.guarded_rmdir)
        _install(originals, os, "mkdir", self.guarded_mkdir)
        _install(originals, os, "rename", self.guarded_rename)
        _install(originals, os, "replace", self.guarded_replace)
        _install(originals, os, "symlink", self.guarded_symlink)
        _install(originals, os, "link", self.guarded_link)
        _install(originals, os, "chmod", self.guarded_chmod)
        _install(originals, os, "utime", self.guarded_utime)
        _install(originals, os, "truncate", self.guarded_truncate)
        _install(originals, os, "chdir", self.guarded_chdir)
        return originals

    def _check_write(self, value: object, operation: str) -> None:
        _require_path(value, (self._root,), operation)

    def _check_read(self, value: object, operation: str) -> None:
        _require_path(value, self._read_roots, operation, allow_missing=True)

    def guarded_open(
        self,
        file: Any,
        mode: str = "r",
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
        closefd: bool = True,
        opener: Any = None,
    ) -> Any:
        if _is_write_mode(mode):
            self._check_write(file, "open")
        else:
            self._check_read(file, "open")
        if opener is not None:
            raise _violation(
                code="SANDBOX_PATH_DENIED",
                message="Custom openers are not supported in the sandbox",
                operation="open",
            )
        return self._original_open(file, mode, buffering, encoding, errors, newline, closefd)

    def guarded_io_open(
        self,
        file: Any,
        mode: str = "r",
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
        closefd: bool = True,
        opener: Any = None,
    ) -> Any:
        if _is_write_mode(mode):
            self._check_write(file, "io.open")
        else:
            self._check_read(file, "io.open")
        if opener is not None:
            raise _violation(
                code="SANDBOX_PATH_DENIED",
                message="Custom openers are not supported in the sandbox",
                operation="io.open",
            )
        return self._original_io_open(file, mode, buffering, encoding, errors, newline, closefd)

    def guarded_os_open(
        self,
        path: Any,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if dir_fd is not None:
            _reject_dir_fd("os.open")
        write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
        if flags & write_flags:
            self._check_write(path, "os.open")
        else:
            self._check_read(path, "os.open")
        return self._original_os_open(path, flags, mode)

    def guarded_listdir(self, path: Any = ".") -> Any:
        self._check_read(path, "os.listdir")
        return self._original_listdir(path)

    def guarded_scandir(self, path: Any = ".") -> Any:
        self._check_read(path, "os.scandir")
        return self._original_scandir(path)

    def guarded_remove(self, path: Any, *, dir_fd: int | None = None) -> None:
        if dir_fd is not None:
            _reject_dir_fd("os.remove")
        self._check_write(path, "os.remove")
        self._original_remove(path)

    def guarded_unlink(self, path: Any, *, dir_fd: int | None = None) -> None:
        if dir_fd is not None:
            _reject_dir_fd("os.unlink")
        self._check_write(path, "os.unlink")
        self._original_unlink(path)

    def guarded_rmdir(self, path: Any, *, dir_fd: int | None = None) -> None:
        if dir_fd is not None:
            _reject_dir_fd("os.rmdir")
        self._check_write(path, "os.rmdir")
        self._original_rmdir(path)

    def guarded_mkdir(self, path: Any, mode: int = 0o777, *, dir_fd: int | None = None) -> None:
        if dir_fd is not None:
            _reject_dir_fd("os.mkdir")
        self._check_write(path, "os.mkdir")
        self._original_mkdir(path, mode)

    def guarded_rename(
        self,
        src: Any,
        dst: Any,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        if src_dir_fd is not None or dst_dir_fd is not None:
            _reject_dir_fd("os.rename")
        self._check_write(src, "os.rename")
        self._check_write(dst, "os.rename")
        self._original_rename(src, dst)

    def guarded_replace(
        self,
        src: Any,
        dst: Any,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        if src_dir_fd is not None or dst_dir_fd is not None:
            _reject_dir_fd("os.replace")
        self._check_write(src, "os.replace")
        self._check_write(dst, "os.replace")
        self._original_replace(src, dst)

    def guarded_symlink(
        self,
        src: Any,
        dst: Any,
        target_is_directory: bool = False,
        *,
        dir_fd: int | None = None,
    ) -> None:
        if dir_fd is not None:
            _reject_dir_fd("os.symlink")
        self._check_write(dst, "os.symlink")
        source = _path_from(src)
        target = _path_from(dst)
        if source is not None and target is not None:
            if source.is_absolute():
                _require_path(source, (self._root,), "os.symlink target")
            else:
                parent = target if target.is_absolute() else Path.cwd() / target
                _require_path(parent.parent / source, (self._root,), "os.symlink target")
        self._original_symlink(src, dst, target_is_directory)

    def guarded_link(
        self,
        src: Any,
        dst: Any,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        if src_dir_fd is not None or dst_dir_fd is not None:
            _reject_dir_fd("os.link")
        self._check_write(src, "os.link")
        self._check_write(dst, "os.link")
        self._original_link(src, dst)

    def guarded_chmod(
        self,
        path: Any,
        mode: int,
        *,
        dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> None:
        if dir_fd is not None:
            _reject_dir_fd("os.chmod")
        self._check_write(path, "os.chmod")
        self._original_chmod(path, mode, follow_symlinks=follow_symlinks)

    def guarded_utime(
        self,
        path: Any,
        times: Any = None,
        *,
        ns: Any = None,
        dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> None:
        if dir_fd is not None:
            _reject_dir_fd("os.utime")
        self._check_write(path, "os.utime")
        if ns is not None:
            self._original_utime(path, ns=ns, follow_symlinks=follow_symlinks)
        else:
            self._original_utime(path, times, follow_symlinks=follow_symlinks)

    def guarded_truncate(self, path: Any, length: int) -> None:
        self._check_write(path, "os.truncate")
        self._original_truncate(path, length)

    def guarded_chdir(self, path: Any) -> None:
        self._check_write(path, "os.chdir")
        self._original_chdir(path)


@contextmanager
def workspace_filesystem_guard(workspace: Path) -> Iterator[None]:
    """Allow file content access below ``workspace`` plus read-only runtime paths.

    Metadata operations such as ``stat`` remain available because the import
    machinery needs them; reads, writes, mutations, and symlink creation are
    checked. Writes and mutations are always confined to the workspace.
    """
    guard = _WorkspaceFilesystemGuard(workspace)
    originals = guard.install()
    try:
        yield
    finally:
        _restore(originals)


@contextmanager
def network_guard() -> Iterator[None]:
    """Reject outbound socket connections and name resolution."""
    originals: list[tuple[object, str, Any]] = []

    def blocked(*_args: object, **_kwargs: object) -> None:
        raise _violation(
            code="SANDBOX_NETWORK_DENIED",
            message="Network access is disabled in the sandbox",
            operation="network",
        )

    try:
        _install(originals, socket, "create_connection", blocked)
        _install(originals, socket, "getaddrinfo", blocked)
        _install(originals, socket, "gethostbyname", blocked)
        _install(originals, socket, "gethostbyname_ex", blocked)
        _install(originals, socket, "gethostbyaddr", blocked)
        _install(originals, socket.socket, "connect", blocked)
        _install(originals, socket.socket, "connect_ex", blocked)
        _install(originals, socket.socket, "bind", blocked)
        _install(originals, socket.socket, "listen", blocked)
        _install(originals, socket.socket, "sendto", blocked)
        if hasattr(socket.socket, "sendmsg"):
            _install(originals, socket.socket, "sendmsg", blocked)
        yield
    finally:
        _restore(originals)


__all__ = ["network_guard", "workspace_filesystem_guard"]
