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


@contextmanager
def workspace_filesystem_guard(workspace: Path) -> Iterator[None]:
    """Allow file content access below ``workspace`` plus read-only runtime paths.

    Metadata operations such as ``stat`` remain available because the import
    machinery needs them; reads, writes, mutations, and symlink creation are
    checked. Writes and mutations are always confined to the workspace.
    """
    root = workspace.resolve()
    read_roots = (root, *_runtime_read_roots())
    originals: list[tuple[object, str, Any]] = []
    original_open = builtins.open
    original_io_open = io.open
    original_os_open = os.open
    original_listdir = os.listdir
    original_scandir = os.scandir
    original_remove = os.remove
    original_unlink = os.unlink
    original_rmdir = os.rmdir
    original_mkdir = os.mkdir
    original_rename = os.rename
    original_replace = os.replace
    original_symlink = os.symlink
    original_link = os.link
    original_chmod = os.chmod
    original_utime = os.utime
    original_truncate = os.truncate
    original_chdir = os.chdir

    def check_write(value: object, operation: str) -> None:
        _require_path(value, (root,), operation)

    def check_read(value: object, operation: str) -> None:
        _require_path(value, read_roots, operation, allow_missing=True)

    def guarded_open(
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
            check_write(file, "open")
        else:
            check_read(file, "open")
        if opener is not None:
            raise _violation(
                code="SANDBOX_PATH_DENIED",
                message="Custom openers are not supported in the sandbox",
                operation="open",
            )
        return original_open(file, mode, buffering, encoding, errors, newline, closefd)

    def guarded_io_open(
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
            check_write(file, "io.open")
        else:
            check_read(file, "io.open")
        if opener is not None:
            raise _violation(
                code="SANDBOX_PATH_DENIED",
                message="Custom openers are not supported in the sandbox",
                operation="io.open",
            )
        return original_io_open(file, mode, buffering, encoding, errors, newline, closefd)

    def guarded_os_open(
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
            check_write(path, "os.open")
        else:
            check_read(path, "os.open")
        return original_os_open(path, flags, mode)

    def guarded_listdir(path: Any = ".") -> Any:
        check_read(path, "os.listdir")
        return original_listdir(path)

    def guarded_scandir(path: Any = ".") -> Any:
        check_read(path, "os.scandir")
        return original_scandir(path)

    def guarded_remove(path: Any, *, dir_fd: int | None = None) -> None:
        if dir_fd is not None:
            _reject_dir_fd("os.remove")
        check_write(path, "os.remove")
        original_remove(path)

    def guarded_unlink(path: Any, *, dir_fd: int | None = None) -> None:
        if dir_fd is not None:
            _reject_dir_fd("os.unlink")
        check_write(path, "os.unlink")
        original_unlink(path)

    def guarded_rmdir(path: Any, *, dir_fd: int | None = None) -> None:
        if dir_fd is not None:
            _reject_dir_fd("os.rmdir")
        check_write(path, "os.rmdir")
        original_rmdir(path)

    def guarded_mkdir(path: Any, mode: int = 0o777, *, dir_fd: int | None = None) -> None:
        if dir_fd is not None:
            _reject_dir_fd("os.mkdir")
        check_write(path, "os.mkdir")
        original_mkdir(path, mode)

    def guarded_rename(
        src: Any,
        dst: Any,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        if src_dir_fd is not None or dst_dir_fd is not None:
            _reject_dir_fd("os.rename")
        check_write(src, "os.rename")
        check_write(dst, "os.rename")
        original_rename(src, dst)

    def guarded_replace(
        src: Any,
        dst: Any,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        if src_dir_fd is not None or dst_dir_fd is not None:
            _reject_dir_fd("os.replace")
        check_write(src, "os.replace")
        check_write(dst, "os.replace")
        original_replace(src, dst)

    def guarded_symlink(
        src: Any,
        dst: Any,
        target_is_directory: bool = False,
        *,
        dir_fd: int | None = None,
    ) -> None:
        if dir_fd is not None:
            _reject_dir_fd("os.symlink")
        check_write(dst, "os.symlink")
        source = _path_from(src)
        target = _path_from(dst)
        if source is not None and target is not None:
            if source.is_absolute():
                _require_path(source, (root,), "os.symlink target")
            else:
                parent = target if target.is_absolute() else Path.cwd() / target
                _require_path(parent.parent / source, (root,), "os.symlink target")
        original_symlink(src, dst, target_is_directory)

    def guarded_link(
        src: Any,
        dst: Any,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        if src_dir_fd is not None or dst_dir_fd is not None:
            _reject_dir_fd("os.link")
        check_write(src, "os.link")
        check_write(dst, "os.link")
        original_link(src, dst)

    def guarded_chmod(
        path: Any,
        mode: int,
        *,
        dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> None:
        if dir_fd is not None:
            _reject_dir_fd("os.chmod")
        check_write(path, "os.chmod")
        original_chmod(path, mode, follow_symlinks=follow_symlinks)

    def guarded_utime(
        path: Any,
        times: Any = None,
        *,
        ns: Any = None,
        dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> None:
        if dir_fd is not None:
            _reject_dir_fd("os.utime")
        check_write(path, "os.utime")
        if ns is not None:
            original_utime(path, ns=ns, follow_symlinks=follow_symlinks)
        else:
            original_utime(path, times, follow_symlinks=follow_symlinks)

    def guarded_truncate(path: Any, length: int) -> None:
        check_write(path, "os.truncate")
        original_truncate(path, length)

    def guarded_chdir(path: Any) -> None:
        check_write(path, "os.chdir")
        original_chdir(path)

    try:
        _install(originals, builtins, "open", guarded_open)
        _install(originals, io, "open", guarded_io_open)
        _install(originals, os, "open", guarded_os_open)
        _install(originals, os, "listdir", guarded_listdir)
        _install(originals, os, "scandir", guarded_scandir)
        _install(originals, os, "remove", guarded_remove)
        _install(originals, os, "unlink", guarded_unlink)
        _install(originals, os, "rmdir", guarded_rmdir)
        _install(originals, os, "mkdir", guarded_mkdir)
        _install(originals, os, "rename", guarded_rename)
        _install(originals, os, "replace", guarded_replace)
        _install(originals, os, "symlink", guarded_symlink)
        _install(originals, os, "link", guarded_link)
        _install(originals, os, "chmod", guarded_chmod)
        _install(originals, os, "utime", guarded_utime)
        _install(originals, os, "truncate", guarded_truncate)
        _install(originals, os, "chdir", guarded_chdir)
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
