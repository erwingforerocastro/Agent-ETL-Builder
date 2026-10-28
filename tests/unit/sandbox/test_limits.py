"""Unit tests for sandbox limit invariants."""

import pytest

from infrastructure.sandbox import SandboxLimits


def test_sandbox_limits_accept_zero_to_disable_checks() -> None:
    limits = SandboxLimits(timeout_seconds=0, memory_mb=0, max_cpu_percent=0)

    assert limits.timeout_seconds == 0
    assert limits.memory_mb == 0
    assert limits.max_cpu_percent == 0


def test_sandbox_limits_reject_negative_timeout() -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        SandboxLimits(timeout_seconds=-1)


def test_sandbox_limits_reject_non_finite_timeout() -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        SandboxLimits(timeout_seconds=float("nan"))


def test_sandbox_limits_reject_negative_memory() -> None:
    with pytest.raises(ValueError, match="memory_mb"):
        SandboxLimits(memory_mb=-1)


@pytest.mark.parametrize("value", [-1, 101])
def test_sandbox_limits_reject_invalid_cpu_percentage(value: int) -> None:
    with pytest.raises(ValueError, match="max_cpu_percent"):
        SandboxLimits(max_cpu_percent=value)
