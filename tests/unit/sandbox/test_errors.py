"""Unit tests for sandbox error contracts."""

from domain.errors import EtlError
from infrastructure.sandbox import SandboxTimeoutError, SandboxViolationError


def test_sandbox_timeout_error_is_structured() -> None:
    error = SandboxTimeoutError()

    assert isinstance(error, EtlError)
    assert error.code == "SANDBOX_TIMEOUT"
    assert error.to_dict()["type"] == "SandboxTimeoutError"


def test_sandbox_violation_error_accepts_overrides() -> None:
    error = SandboxViolationError(code="SANDBOX_NETWORK", message="Network is disabled")

    assert error.code == "SANDBOX_NETWORK"
    assert error.message == "Network is disabled"
    assert error.retryable is False
