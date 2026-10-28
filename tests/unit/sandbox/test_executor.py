"""Unit tests for the sandbox executor."""

from infrastructure.sandbox import SandboxExecutor, SandboxLimits
from infrastructure.sandbox.executor import timeout_context


def test_sandbox_executor_runs_a_callable() -> None:
    executor = SandboxExecutor(SandboxLimits(timeout_seconds=0))

    assert executor.run(lambda value: value + 1, 1) == 2


def test_timeout_context_yields_when_timeout_is_disabled() -> None:
    with timeout_context(0):
        pass


def test_timeout_context_yields_when_signals_are_unavailable() -> None:
    with timeout_context(1):
        pass
