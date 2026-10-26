"""Environment-backed runtime settings."""

import os
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import Final, Literal, Self, cast

Environment = Literal["local", "test", "production"]

_DISTRIBUTION_NAME: Final[str] = "agent-etl-builder"
_VALID_ENVIRONMENTS: Final[frozenset[str]] = frozenset({"local", "test", "production"})


def _distribution_version() -> str:
    try:
        return version(_DISTRIBUTION_NAME)
    except PackageNotFoundError:
        return "0.0.0"


@dataclass(frozen=True, slots=True)
class Settings:
    service_name: str
    version: str
    environment: Environment

    def __post_init__(self) -> None:
        if not self.service_name.strip():
            raise ValueError("service_name must not be blank")
        if not self.version.strip():
            raise ValueError("version must not be blank")
        if self.environment not in _VALID_ENVIRONMENTS:
            raise ValueError(f"unsupported environment: {self.environment}")

    @classmethod
    def from_env(cls) -> Self:
        environment = os.getenv("AGENT_ETL_ENVIRONMENT", "local").strip().lower()
        return cls(
            service_name=os.getenv("AGENT_ETL_SERVICE_NAME", "agent-etl-builder"),
            version=_distribution_version(),
            environment=cast(Environment, environment),
        )
