"""Environment-backed runtime settings."""

import math
import os
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import Final, Literal, Self, cast

from domain.entities.run import CleanupPolicy

Environment = Literal["local", "test", "production"]

_DISTRIBUTION_NAME: Final[str] = "agent-etl-builder"
_VALID_ENVIRONMENTS: Final[frozenset[str]] = frozenset({"local", "test", "production"})
_DEFAULT_APPROVAL_TIMEOUT_SECONDS: Final[float] = 300.0
_DEFAULT_MAX_REQUEST_BYTES: Final[int] = 1_000_000


def _distribution_version() -> str:
    try:
        return version(_DISTRIBUTION_NAME)
    except PackageNotFoundError:
        return "0.0.0"


def _approval_timeout_from_env() -> float:
    raw = os.getenv("AGENT_ETL_APPROVAL_TIMEOUT_SECONDS", "300").strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError("AGENT_ETL_APPROVAL_TIMEOUT_SECONDS must be a number") from exc
    if not math.isfinite(value) or value <= 0:
        raise ValueError("AGENT_ETL_APPROVAL_TIMEOUT_SECONDS must be finite and positive")
    return value


def _cleanup_policy_from_env() -> CleanupPolicy:
    raw = os.getenv("AGENT_ETL_CLEANUP_POLICY", CleanupPolicy.CLEANUP.value).strip().lower()
    try:
        return CleanupPolicy(raw)
    except ValueError as exc:
        raise ValueError(f"unsupported cleanup policy: {raw}") from exc


def _api_key_from_env() -> str | None:
    raw = os.getenv("AGENT_ETL_API_KEY", "").strip()
    return raw or None


def _max_request_bytes_from_env() -> int:
    raw = os.getenv("AGENT_ETL_MAX_REQUEST_BYTES", "1000000").strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("AGENT_ETL_MAX_REQUEST_BYTES must be an integer") from exc
    if value <= 0:
        raise ValueError("AGENT_ETL_MAX_REQUEST_BYTES must be positive")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    service_name: str
    version: str
    environment: Environment
    approval_timeout_seconds: float = _DEFAULT_APPROVAL_TIMEOUT_SECONDS
    cleanup_policy: CleanupPolicy = CleanupPolicy.CLEANUP
    max_request_bytes: int = _DEFAULT_MAX_REQUEST_BYTES
    api_key: str | None = None

    def __post_init__(self) -> None:
        if not self.service_name.strip():
            raise ValueError("service_name must not be blank")
        if not self.version.strip():
            raise ValueError("version must not be blank")
        if self.environment not in _VALID_ENVIRONMENTS:
            raise ValueError(f"unsupported environment: {self.environment}")
        if not math.isfinite(self.approval_timeout_seconds) or self.approval_timeout_seconds <= 0:
            raise ValueError("approval_timeout_seconds must be finite and positive")
        if not isinstance(self.cleanup_policy, CleanupPolicy):
            raise ValueError("cleanup_policy must be a CleanupPolicy")
        if self.max_request_bytes <= 0:
            raise ValueError("max_request_bytes must be positive")
        if self.api_key is not None and not self.api_key.strip():
            raise ValueError("api_key must not be blank when provided")

    @classmethod
    def from_env(cls) -> Self:
        environment = os.getenv("AGENT_ETL_ENVIRONMENT", "local").strip().lower()
        return cls(
            service_name=os.getenv("AGENT_ETL_SERVICE_NAME", "agent-etl-builder"),
            version=_distribution_version(),
            environment=cast(Environment, environment),
            approval_timeout_seconds=_approval_timeout_from_env(),
            cleanup_policy=_cleanup_policy_from_env(),
            max_request_bytes=_max_request_bytes_from_env(),
            api_key=_api_key_from_env(),
        )


__all__ = ["Settings"]
