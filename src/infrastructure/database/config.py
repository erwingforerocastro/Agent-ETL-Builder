"""PostgreSQL connection configuration without driver imports."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final, Literal

SslMode = Literal["disable", "allow", "prefer", "require", "verify-ca", "verify-full"]

SSL_MODES: Final[frozenset[str]] = frozenset(
    {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}
)
DEFAULT_APPLICATION_NAME: Final[str] = "agent-etl-builder"
DEFAULT_CONNECT_TIMEOUT_SECONDS: Final[int] = 10
DEFAULT_STATEMENT_TIMEOUT_MS: Final[int] = 30_000


@dataclass(frozen=True, slots=True)
class PostgresConfig:
    """Connection parameters for the PostgreSQL adapter."""

    dsn: str = field(repr=False)
    sslmode: SslMode = "prefer"
    sslrootcert: str | None = None
    connect_timeout_seconds: int = DEFAULT_CONNECT_TIMEOUT_SECONDS
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS
    application_name: str = DEFAULT_APPLICATION_NAME

    def __post_init__(self) -> None:
        if not self.dsn.strip():
            raise ValueError("dsn must not be blank")
        if self.sslmode not in SSL_MODES:
            raise ValueError(f"unsupported sslmode: {self.sslmode}")
        if self.sslrootcert is not None and not self.sslrootcert.strip():
            raise ValueError("sslrootcert must not be blank when provided")
        if self.connect_timeout_seconds <= 0:
            raise ValueError("connect_timeout_seconds must be positive")
        if self.statement_timeout_ms <= 0:
            raise ValueError("statement_timeout_ms must be positive")
        if not self.application_name.strip():
            raise ValueError("application_name must not be blank")


__all__ = [
    "DEFAULT_APPLICATION_NAME",
    "DEFAULT_CONNECT_TIMEOUT_SECONDS",
    "DEFAULT_STATEMENT_TIMEOUT_MS",
    "SSL_MODES",
    "PostgresConfig",
    "SslMode",
]
