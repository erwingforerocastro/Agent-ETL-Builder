"""Unit tests for the sandbox executor and its guards."""

import builtins
import os
import socket
import sys
import time
from pathlib import Path

import pandas as pd
import pytest

from infrastructure.loaders.csv import save_csv
from infrastructure.sandbox import (
    SandboxExecutor,
    SandboxLimits,
    SandboxMemoryError,
    SandboxTimeoutError,
    SandboxViolationError,
)
from infrastructure.sandbox.executor import timeout_context
from infrastructure.sandbox.guards import network_guard, workspace_filesystem_guard


def _add(value: int) -> int:
    return value + 1


def _write_file(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _read_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _open_with_os(path: Path) -> int:
    return os.open(path, os.O_RDONLY)


def _connect() -> None:
    socket.create_connection(("example.com", 80), timeout=0.1)


def _socket_guard_active() -> bool:
    return getattr(socket.create_connection, "__name__", "") == "blocked"


def _bind_socket() -> None:
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", 0))
    finally:
        sock.close()


def _allocate(megabytes: int) -> str:
    return "x" * (megabytes * 1024 * 1024)


def _busy_loop() -> None:
    while True:
        pass


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _cwd() -> Path:
    return Path.cwd()


def _chdir(path: Path) -> None:
    os.chdir(path)


def _listdir(path: Path) -> list[str]:
    return os.listdir(path)


def _rename(src: Path, dst: Path) -> None:
    os.rename(src, dst)


def _mkdir(path: Path) -> None:
    os.mkdir(path)


def _remove(path: Path) -> None:
    os.remove(path)


def _open_with_custom_opener(path: Path) -> None:
    builtins.open(path, opener=os.open).close()


def _read_byte(path: Path) -> bytes:
    with open(path, "rb") as handle:
        return handle.read(1)


def _fail() -> None:
    raise ValueError("boom")


def _executor(
    tmp_path: Path,
    *,
    timeout_seconds: float = 0,
    memory_mb: int = 0,
    allow_network: bool = False,
) -> SandboxExecutor:
    limits = SandboxLimits(
        timeout_seconds=timeout_seconds,
        memory_mb=memory_mb,
        allow_network=allow_network,
    )
    return SandboxExecutor(limits, workspace=tmp_path)


def test_sandbox_executor_runs_a_callable(tmp_path: Path) -> None:
    assert _executor(tmp_path).run(_add, 1) == 2


def test_sandbox_executor_runs_with_workspace_as_cwd(tmp_path: Path) -> None:
    original = Path.cwd()

    assert _executor(tmp_path).run(_cwd) == tmp_path.resolve()
    assert Path.cwd() == original


def test_sandbox_executor_allows_files_inside_workspace(tmp_path: Path) -> None:
    target = tmp_path / "output.txt"

    _executor(tmp_path).run(_write_file, target, "ok")

    assert target.read_text(encoding="utf-8") == "ok"


def test_sandbox_executor_denies_reads_outside_workspace(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("secret", encoding="utf-8")
    try:
        with pytest.raises(SandboxViolationError) as caught:
            _executor(tmp_path).run(_read_file, outside)
    finally:
        outside.unlink(missing_ok=True)

    assert caught.value.code == "SANDBOX_PATH_DENIED"
    assert caught.value.context["operation"] in {"open", "io.open"}


def test_sandbox_executor_denies_writes_outside_workspace(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-escaped.txt"

    with pytest.raises(SandboxViolationError) as caught:
        _executor(tmp_path).run(_write_file, outside, "escaped")

    assert caught.value.code == "SANDBOX_PATH_DENIED"
    assert not outside.exists()


def test_sandbox_executor_denies_traversal_outside_workspace(tmp_path: Path) -> None:
    outside = tmp_path / ".." / f"{tmp_path.name}-traversal.txt"

    with pytest.raises(SandboxViolationError):
        _executor(tmp_path).run(_write_file, outside, "escaped")

    assert not outside.resolve().exists()


def test_sandbox_executor_denies_os_open_outside_workspace(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-os-open.txt"
    outside.write_text("secret", encoding="utf-8")
    try:
        with pytest.raises(SandboxViolationError) as caught:
            _executor(tmp_path).run(_open_with_os, outside)
    finally:
        outside.unlink(missing_ok=True)

    assert caught.value.context["operation"] == "os.open"


def test_sandbox_executor_blocks_network_access(tmp_path: Path) -> None:
    with pytest.raises(SandboxViolationError) as caught:
        _executor(tmp_path).run(_connect)

    assert caught.value.code == "SANDBOX_NETWORK_DENIED"


def test_sandbox_executor_blocks_inbound_network_access(tmp_path: Path) -> None:
    with pytest.raises(SandboxViolationError) as caught:
        _executor(tmp_path).run(_bind_socket)

    assert caught.value.code == "SANDBOX_NETWORK_DENIED"


def test_sandbox_executor_can_enable_network(tmp_path: Path) -> None:
    executor = _executor(tmp_path, allow_network=True)

    assert executor.run(_socket_guard_active) is False


def test_sandbox_executor_enforces_memory_limit(tmp_path: Path) -> None:
    executor = _executor(tmp_path, memory_mb=1)

    with pytest.raises(SandboxMemoryError) as caught:
        executor.run(_allocate, 2)

    assert caught.value.code == "SANDBOX_MEMORY_LIMIT"
    assert caught.value.context["limit_mb"] == 1


def test_sandbox_executor_enforces_timeout(tmp_path: Path) -> None:
    executor = _executor(tmp_path, timeout_seconds=0.05)

    with pytest.raises(SandboxTimeoutError) as caught:
        executor.run(_busy_loop)

    assert caught.value.code == "SANDBOX_TIMEOUT"


def test_sandbox_executor_restores_guards_after_failure(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-after-failure.txt"
    executor = _executor(tmp_path)

    with pytest.raises(SandboxViolationError):
        executor.run(_write_file, outside, "escaped")

    assert getattr(socket.create_connection, "__name__", "") != "blocked"
    outside.write_text("allowed", encoding="utf-8")
    try:
        assert outside.read_text(encoding="utf-8") == "allowed"
    finally:
        outside.unlink(missing_ok=True)


def test_timeout_context_yields_when_timeout_is_disabled() -> None:
    with timeout_context(0):
        pass


def test_timeout_context_raises_after_sleep() -> None:
    with pytest.raises(SandboxTimeoutError), timeout_context(0.01):
        _sleep(0.1)


def test_workspace_guard_allows_inside_and_restores(tmp_path: Path) -> None:
    target = tmp_path / "inside.txt"

    with workspace_filesystem_guard(tmp_path):
        target.write_text("inside", encoding="utf-8")

    assert target.read_text(encoding="utf-8") == "inside"


def test_network_guard_blocks_and_restores() -> None:
    original = socket.create_connection

    with pytest.raises(SandboxViolationError), network_guard():
        socket.create_connection(("example.com", 80))

    assert socket.create_connection is original


def test_sandbox_executor_allows_runtime_reads(tmp_path: Path) -> None:
    assert _executor(tmp_path).run(_read_byte, Path(sys.executable))


def test_sandbox_executor_allows_missing_outside_reads_to_fail_normally(tmp_path: Path) -> None:
    missing = tmp_path.parent / f"{tmp_path.name}-missing.txt"

    with pytest.raises(FileNotFoundError):
        _executor(tmp_path).run(_read_file, missing)


def test_sandbox_executor_rejects_custom_openers(tmp_path: Path) -> None:
    target = tmp_path / "inside.txt"
    target.write_text("inside", encoding="utf-8")

    with pytest.raises(SandboxViolationError) as caught:
        _executor(tmp_path).run(_open_with_custom_opener, target)

    assert "openers" in caught.value.message


def test_sandbox_executor_denies_chdir_outside_workspace(tmp_path: Path) -> None:
    original = Path.cwd()

    with pytest.raises(SandboxViolationError):
        _executor(tmp_path).run(_chdir, tmp_path.parent)

    assert Path.cwd() == original


def test_sandbox_executor_denies_listing_outside_workspace(tmp_path: Path) -> None:
    with pytest.raises(SandboxViolationError):
        _executor(tmp_path).run(_listdir, tmp_path.parent)


def test_sandbox_executor_denies_rename_outside_workspace(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("source", encoding="utf-8")
    outside = tmp_path.parent / f"{tmp_path.name}-renamed.txt"

    with pytest.raises(SandboxViolationError):
        _executor(tmp_path).run(_rename, source, outside)

    assert source.exists()
    assert not outside.exists()


def test_sandbox_executor_denies_mkdir_outside_workspace(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-new-dir"

    with pytest.raises(SandboxViolationError):
        _executor(tmp_path).run(_mkdir, outside)

    assert not outside.exists()


def test_sandbox_executor_denies_remove_outside_workspace(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-do-not-delete.txt"
    outside.write_text("keep", encoding="utf-8")
    try:
        with pytest.raises(SandboxViolationError):
            _executor(tmp_path).run(_remove, outside)
        assert outside.exists()
    finally:
        outside.unlink(missing_ok=True)


def test_sandbox_executor_surfaces_loader_violations(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-loader.csv"
    frame = pd.DataFrame({"name": ["Ada"]})

    with pytest.raises(SandboxViolationError):
        _executor(tmp_path).run(save_csv, frame, path=str(outside))

    assert not outside.exists()


def test_sandbox_executor_propagates_callable_errors(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="boom"):
        _executor(tmp_path).run(_fail)


def test_sandbox_executor_requires_workspace_when_workspace_only() -> None:
    with pytest.raises(ValueError, match="workspace is required"):
        SandboxExecutor(SandboxLimits())


def test_sandbox_executor_rejects_missing_workspace(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="existing directory"):
        SandboxExecutor(SandboxLimits(), workspace=tmp_path / "missing")


def test_sandbox_executor_can_disable_workspace_guard() -> None:
    executor = SandboxExecutor(SandboxLimits(timeout_seconds=0, memory_mb=0, workspace_only=False))

    assert executor.run(_add, 1) == 2


def test_timeout_restores_cwd_and_guards(tmp_path: Path) -> None:
    original_cwd = Path.cwd()
    original_open = builtins.open

    with pytest.raises(SandboxTimeoutError):
        _executor(tmp_path, timeout_seconds=0.01).run(_busy_loop)

    assert Path.cwd() == original_cwd
    assert builtins.open is original_open
