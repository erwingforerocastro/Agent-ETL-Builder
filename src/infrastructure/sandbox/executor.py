"""Sandboxed execution with workspace, network, memory, and time guards."""

from __future__ import annotations

import ctypes
import os
import signal
import threading
import tracemalloc
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import FrameType
from typing import Any, cast

from infrastructure.sandbox.errors import SandboxMemoryError, SandboxTimeoutError
from infrastructure.sandbox.guards import network_guard, workspace_filesystem_guard
from infrastructure.sandbox.limits import SandboxLimits

_EXECUTION_LOCK = threading.RLock()


class _SandboxDeadlineExceeded(BaseException):
    """Internal signal used to stop a callable at its deadline."""


def _async_raise(thread_id: int, exception: type[BaseException]) -> bool:
    """Raise ``exception`` in another CPython thread when possible."""
    set_async_exc = getattr(ctypes.pythonapi, "PyThreadState_SetAsyncExc", None)
    if set_async_exc is None:
        return False
    set_async_exc.argtypes = [ctypes.c_ulong, ctypes.py_object]
    set_async_exc.restype = ctypes.c_int
    result = cast(int, set_async_exc(ctypes.c_ulong(thread_id), ctypes.py_object(exception)))
    return result == 1


def _start_signal_timeout(seconds: float) -> Callable[[], None]:
    setitimer = cast(
        Callable[..., tuple[float, float]],
        signal.setitimer,  # type: ignore[attr-defined]
    )
    itimer_real = cast(int, signal.ITIMER_REAL)  # type: ignore[attr-defined]

    previous = setitimer(itimer_real, seconds)

    def stop_timer() -> None:
        setitimer(itimer_real, previous[0], previous[1])

    return stop_timer


def _supports_signal_timeout() -> bool:
    return (
        threading.current_thread() is threading.main_thread()
        and hasattr(signal, "SIGALRM")
        and hasattr(signal, "setitimer")
    )


@contextmanager
def timeout_context(seconds: float) -> Iterator[None]:
    """Bound the enclosed block by wall-clock time.

    Unix main threads use ``setitimer``/``SIGALRM``. Other threads and
    platforms use a watchdog thread plus a CPython async exception. The async
    exception cannot interrupt a callable that is blocked inside native code;
    that limitation is documented in ``documents/security.txt``.
    """
    if seconds <= 0:
        yield
        return

    if _supports_signal_timeout():
        sigalrm = cast(int, signal.SIGALRM)  # type: ignore[attr-defined]
        previous_handler = signal.getsignal(sigalrm)

        def handler(_signum: int, _frame: FrameType | None) -> None:
            raise _SandboxDeadlineExceeded

        signal.signal(sigalrm, handler)
        stop_timer: Callable[[], None] | None = None
        try:
            stop_timer = _start_signal_timeout(seconds)
            try:
                yield
            except _SandboxDeadlineExceeded as exc:
                raise SandboxTimeoutError(
                    context={"timeout_seconds": seconds},
                ) from exc
        finally:
            if stop_timer is not None:
                stop_timer()
            signal.signal(sigalrm, previous_handler)
        return

    finished = threading.Event()
    expired = threading.Event()
    target_thread = threading.get_ident()

    def watchdog() -> None:
        if finished.wait(seconds):
            return
        expired.set()
        _async_raise(target_thread, _SandboxDeadlineExceeded)

    watchdog_thread = threading.Thread(
        target=watchdog,
        name="sandbox-timeout",
        daemon=True,
    )
    watchdog_thread.start()
    try:
        try:
            yield
        except _SandboxDeadlineExceeded as exc:
            raise SandboxTimeoutError(
                context={"timeout_seconds": seconds},
            ) from exc
    finally:
        finished.set()
        watchdog_thread.join(timeout=1.0)

    if expired.is_set():
        raise SandboxTimeoutError(context={"timeout_seconds": seconds})


@contextmanager
def memory_guard(limit_mb: int) -> Iterator[None]:
    """Reject an execution whose traced Python peak exceeds ``limit_mb``."""
    if limit_mb <= 0:
        yield
        return

    started_here = not tracemalloc.is_tracing()
    if started_here:
        tracemalloc.start()
    else:
        tracemalloc.reset_peak()

    peak = 0
    try:
        yield
        _, peak = tracemalloc.get_traced_memory()
    finally:
        if started_here:
            tracemalloc.stop()

    limit_bytes = limit_mb * 1024 * 1024
    if peak > limit_bytes:
        raise SandboxMemoryError(
            context={
                "limit_mb": limit_mb,
                "peak_mb": round(peak / (1024 * 1024), 3),
            }
        )


class SandboxExecutor:
    """Runs allowlisted callables under process-local resource guards."""

    def __init__(
        self,
        limits: SandboxLimits | None = None,
        *,
        workspace: Path | None = None,
    ) -> None:
        self.limits = limits or SandboxLimits()
        self._workspace = workspace.resolve() if workspace is not None else None
        if self.limits.workspace_only:
            if self._workspace is None:
                raise ValueError("workspace is required when workspace_only is enabled")
            if not self._workspace.is_dir():
                raise ValueError("workspace must be an existing directory")

    def run(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        with _EXECUTION_LOCK:
            try:
                return self._run_guarded(func, *args, **kwargs)
            except _SandboxDeadlineExceeded as exc:
                raise SandboxTimeoutError(
                    context={"timeout_seconds": self.limits.timeout_seconds},
                ) from exc

    def _run_guarded(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        previous_cwd = Path.cwd()
        workspace = self._workspace
        try:
            if workspace is not None:
                os.chdir(workspace)

            with ExitStack() as stack:
                if self.limits.workspace_only:
                    if workspace is None:
                        raise ValueError("workspace is required when workspace_only is enabled")
                    stack.enter_context(workspace_filesystem_guard(workspace))
                if not self.limits.allow_network:
                    stack.enter_context(network_guard())

                with (
                    memory_guard(self.limits.memory_mb),
                    timeout_context(self.limits.timeout_seconds),
                ):
                    try:
                        return func(*args, **kwargs)
                    except _SandboxDeadlineExceeded as exc:
                        raise SandboxTimeoutError(
                            context={
                                "timeout_seconds": self.limits.timeout_seconds,
                            }
                        ) from exc
        finally:
            os.chdir(previous_cwd)


__all__ = ["SandboxExecutor", "memory_guard", "timeout_context"]
