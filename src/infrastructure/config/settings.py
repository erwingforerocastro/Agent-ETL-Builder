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


@dataclass(frozen=True, slots=True)
class Settings:
    service_name: str
    version: str
    environment: Environment
    approval_timeout_seconds: float = _DEFAULT_APPROVAL_TIMEOUT_SECONDS
    cleanup_policy: CleanupPolicy = CleanupPolicy.CLEANUP

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

    @classmethod
    def from_env(cls) -> Self:
        environment = os.getenv("AGENT_ETL_ENVIRONMENT", "local").strip().lower()
        return cls(
            service_name=os.getenv("AGENT_ETL_SERVICE_NAME", "agent-etl-builder"),
            version=_distribution_version(),
            environment=cast(Environment, environment),
            approval_timeout_seconds=_approval_timeout_from_env(),
            cleanup_policy=_cleanup_policy_from_env(),
        )


__all__ = ["Settings"]
