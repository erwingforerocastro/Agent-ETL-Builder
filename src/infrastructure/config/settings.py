"""Environment-backed runtime settings."""

import math
import os
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version
from typing import Final, Literal, Self, cast
from urllib.parse import urlsplit

from domain.entities.run import CleanupPolicy
from infrastructure.database.config import (
    DEFAULT_APPLICATION_NAME,
    DEFAULT_CONNECT_TIMEOUT_SECONDS,
    DEFAULT_STATEMENT_TIMEOUT_MS,
    SSL_MODES,
    SslMode,
)

Environment = Literal["local", "test", "production"]

_DISTRIBUTION_NAME: Final[str] = "agent-etl-builder"
_VALID_ENVIRONMENTS: Final[frozenset[str]] = frozenset({"local", "test", "production"})
_DEFAULT_APPROVAL_TIMEOUT_SECONDS: Final[float] = 300.0
_DEFAULT_MAX_REQUEST_BYTES: Final[int] = 1_000_000
_DEFAULT_OLLAMA_BASE_URL: Final[str] = "http://127.0.0.1:11434"
_DEFAULT_OLLAMA_TIMEOUT_SECONDS: Final[float] = 90.0


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


def _optional_text_from_env(name: str) -> str | None:
    raw = os.getenv(name, "").strip()
    return raw or None


def _positive_float_from_env(name: str, default: float) -> float:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return value


def _ollama_base_url_from_env() -> str:
    raw = os.getenv("AGENT_ETL_OLLAMA_BASE_URL", _DEFAULT_OLLAMA_BASE_URL).strip()
    return raw.rstrip("/") or _DEFAULT_OLLAMA_BASE_URL


def _positive_int_from_env(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _database_sslmode_from_env() -> SslMode:
    raw = os.getenv("AGENT_ETL_DATABASE_SSLMODE", "prefer").strip().lower()
    if raw not in SSL_MODES:
        raise ValueError(f"unsupported database sslmode: {raw}")
    return cast(SslMode, raw)


@dataclass(frozen=True, slots=True)
class Settings:
    service_name: str
    version: str
    environment: Environment
    approval_timeout_seconds: float = _DEFAULT_APPROVAL_TIMEOUT_SECONDS
    cleanup_policy: CleanupPolicy = CleanupPolicy.CLEANUP
    max_request_bytes: int = _DEFAULT_MAX_REQUEST_BYTES
    database_url: str | None = field(default=None, repr=False)
    database_sslmode: SslMode = "prefer"
    database_sslrootcert: str | None = None
    database_connect_timeout_seconds: int = DEFAULT_CONNECT_TIMEOUT_SECONDS
    database_statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS
    database_application_name: str = DEFAULT_APPLICATION_NAME
    api_key: str | None = field(default=None, repr=False)
    ollama_model: str | None = None
    ollama_base_url: str = _DEFAULT_OLLAMA_BASE_URL
    ollama_timeout_seconds: float = _DEFAULT_OLLAMA_TIMEOUT_SECONDS

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
        if self.database_url is not None and not self.database_url.strip():
            raise ValueError("database_url must not be blank when provided")
        if self.database_sslmode not in SSL_MODES:
            raise ValueError(f"unsupported database sslmode: {self.database_sslmode}")
        if self.database_sslrootcert is not None and not self.database_sslrootcert.strip():
            raise ValueError("database_sslrootcert must not be blank when provided")
        if self.database_connect_timeout_seconds <= 0:
            raise ValueError("database_connect_timeout_seconds must be positive")
        if self.database_statement_timeout_ms <= 0:
            raise ValueError("database_statement_timeout_ms must be positive")
        if not self.database_application_name.strip():
            raise ValueError("database_application_name must not be blank")
        if self.api_key is not None and not self.api_key.strip():
            raise ValueError("api_key must not be blank when provided")
        if self.ollama_model is not None and not self.ollama_model.strip():
            raise ValueError("ollama_model must not be blank when provided")
        parsed_base_url = urlsplit(self.ollama_base_url)
        if (
            parsed_base_url.scheme not in {"http", "https"}
            or not parsed_base_url.netloc
            or parsed_base_url.username is not None
            or parsed_base_url.password is not None
        ):
            raise ValueError("ollama_base_url must be an HTTP(S) URL without credentials")
        if not math.isfinite(self.ollama_timeout_seconds) or self.ollama_timeout_seconds <= 0:
            raise ValueError("ollama_timeout_seconds must be finite and positive")

    @classmethod
    def from_env(cls) -> Self:
        environment = os.getenv("AGENT_ETL_ENVIRONMENT", "local").strip().lower()
        return cls(
            service_name=os.getenv("AGENT_ETL_SERVICE_NAME", "agent-etl-builder"),
            version=_distribution_version(),
            environment=cast(Environment, environment),
            approval_timeout_seconds=_approval_timeout_from_env(),
            cleanup_policy=_cleanup_policy_from_env(),
            max_request_bytes=_positive_int_from_env(
                "AGENT_ETL_MAX_REQUEST_BYTES",
                _DEFAULT_MAX_REQUEST_BYTES,
            ),
            database_url=_optional_text_from_env("AGENT_ETL_DATABASE_URL"),
            database_sslmode=_database_sslmode_from_env(),
            database_sslrootcert=_optional_text_from_env("AGENT_ETL_DATABASE_SSLROOTCERT"),
            database_connect_timeout_seconds=_positive_int_from_env(
                "AGENT_ETL_DATABASE_CONNECT_TIMEOUT_SECONDS",
                DEFAULT_CONNECT_TIMEOUT_SECONDS,
            ),
            database_statement_timeout_ms=_positive_int_from_env(
                "AGENT_ETL_DATABASE_STATEMENT_TIMEOUT_MS",
                DEFAULT_STATEMENT_TIMEOUT_MS,
            ),
            database_application_name=os.getenv(
                "AGENT_ETL_DATABASE_APPLICATION_NAME",
                DEFAULT_APPLICATION_NAME,
            ).strip(),
            api_key=_optional_text_from_env("AGENT_ETL_API_KEY"),
            ollama_model=_optional_text_from_env("AGENT_ETL_OLLAMA_MODEL"),
            ollama_base_url=_ollama_base_url_from_env(),
            ollama_timeout_seconds=_positive_float_from_env(
                "AGENT_ETL_OLLAMA_TIMEOUT_SECONDS",
                _DEFAULT_OLLAMA_TIMEOUT_SECONDS,
            ),
        )


__all__ = ["Settings"]
