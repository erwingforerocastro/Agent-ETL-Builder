from importlib.metadata import PackageNotFoundError, version

import pytest

from domain.entities.run import CleanupPolicy
from infrastructure.config import settings as settings_module
from infrastructure.config.settings import Settings


def test_from_env_uses_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENT_ETL_SERVICE_NAME", raising=False)
    monkeypatch.delenv("AGENT_ETL_ENVIRONMENT", raising=False)
    monkeypatch.delenv("AGENT_ETL_APPROVAL_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("AGENT_ETL_CLEANUP_POLICY", raising=False)
    monkeypatch.delenv("AGENT_ETL_MAX_REQUEST_BYTES", raising=False)
    monkeypatch.delenv("AGENT_ETL_DATABASE_URL", raising=False)
    monkeypatch.delenv("AGENT_ETL_DATABASE_SSLMODE", raising=False)
    monkeypatch.delenv("AGENT_ETL_DATABASE_SSLROOTCERT", raising=False)
    monkeypatch.delenv("AGENT_ETL_DATABASE_CONNECT_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("AGENT_ETL_DATABASE_STATEMENT_TIMEOUT_MS", raising=False)
    monkeypatch.delenv("AGENT_ETL_DATABASE_APPLICATION_NAME", raising=False)
    monkeypatch.delenv("AGENT_ETL_API_KEY", raising=False)

    settings = Settings.from_env()

    assert settings.service_name == "agent-etl-builder"
    assert settings.version == version("agent-etl-builder")
    assert settings.environment == "local"
    assert settings.approval_timeout_seconds == 300
    assert settings.cleanup_policy is CleanupPolicy.CLEANUP
    assert settings.max_request_bytes == 1_000_000
    assert settings.database_url is None
    assert settings.database_sslmode == "prefer"
    assert settings.database_sslrootcert is None
    assert settings.database_connect_timeout_seconds == 10
    assert settings.database_statement_timeout_ms == 30_000
    assert settings.database_application_name == "agent-etl-builder"
    assert settings.api_key is None


def test_from_env_reads_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_ETL_SERVICE_NAME", "custom-service")
    monkeypatch.setenv("AGENT_ETL_ENVIRONMENT", "TEST")
    monkeypatch.setenv("AGENT_ETL_APPROVAL_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("AGENT_ETL_CLEANUP_POLICY", "RETAIN")
    monkeypatch.setenv("AGENT_ETL_MAX_REQUEST_BYTES", "2048")
    monkeypatch.setenv(
        "AGENT_ETL_DATABASE_URL",
        "postgresql://user:secret@localhost:5432/warehouse",
    )
    monkeypatch.setenv("AGENT_ETL_DATABASE_SSLMODE", "VERIFY-FULL")
    monkeypatch.setenv("AGENT_ETL_DATABASE_SSLROOTCERT", "C:/certs/root.crt")
    monkeypatch.setenv("AGENT_ETL_DATABASE_CONNECT_TIMEOUT_SECONDS", "7")
    monkeypatch.setenv("AGENT_ETL_DATABASE_STATEMENT_TIMEOUT_MS", "15000")
    monkeypatch.setenv("AGENT_ETL_DATABASE_APPLICATION_NAME", "custom-agent")
    monkeypatch.setenv("AGENT_ETL_API_KEY", "secret-key")

    settings = Settings.from_env()

    assert settings.service_name == "custom-service"
    assert settings.environment == "test"
    assert settings.approval_timeout_seconds == 12.5
    assert settings.cleanup_policy is CleanupPolicy.RETAIN
    assert settings.max_request_bytes == 2048
    assert settings.database_url == "postgresql://user:secret@localhost:5432/warehouse"
    assert settings.database_sslmode == "verify-full"
    assert settings.database_sslrootcert == "C:/certs/root.crt"
    assert settings.database_connect_timeout_seconds == 7
    assert settings.database_statement_timeout_ms == 15_000
    assert settings.database_application_name == "custom-agent"
    assert settings.api_key == "secret-key"
    assert "secret" not in repr(settings)


def test_from_env_rejects_unknown_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_ETL_ENVIRONMENT", "staging")

    with pytest.raises(ValueError, match="unsupported environment"):
        Settings.from_env()


def test_from_env_falls_back_when_metadata_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing_version(name: str) -> str:
        raise PackageNotFoundError(name)

    monkeypatch.setattr(settings_module, "version", missing_version)

    settings = Settings.from_env()

    assert settings.version == "0.0.0"


def test_from_env_rejects_invalid_approval_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_ETL_APPROVAL_TIMEOUT_SECONDS", "not-a-number")

    with pytest.raises(ValueError, match="AGENT_ETL_APPROVAL_TIMEOUT_SECONDS"):
        Settings.from_env()


def test_from_env_rejects_unknown_cleanup_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_ETL_CLEANUP_POLICY", "delete-everything")

    with pytest.raises(ValueError, match="unsupported cleanup policy"):
        Settings.from_env()


@pytest.mark.parametrize("value", ["not-a-number", "0", "-1"])
def test_from_env_rejects_invalid_max_request_bytes(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("AGENT_ETL_MAX_REQUEST_BYTES", value)

    with pytest.raises(ValueError, match="AGENT_ETL_MAX_REQUEST_BYTES"):
        Settings.from_env()


def test_from_env_rejects_unknown_database_sslmode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_ETL_DATABASE_SSLMODE", "optional")

    with pytest.raises(ValueError, match="unsupported database sslmode"):
        Settings.from_env()


@pytest.mark.parametrize(
    "name",
    [
        "AGENT_ETL_DATABASE_CONNECT_TIMEOUT_SECONDS",
        "AGENT_ETL_DATABASE_STATEMENT_TIMEOUT_MS",
    ],
)
@pytest.mark.parametrize("value", ["not-a-number", "0", "-1"])
def test_from_env_rejects_invalid_database_timeouts(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=name):
        Settings.from_env()


def test_rejects_blank_database_url() -> None:
    with pytest.raises(ValueError, match="database_url"):
        Settings(
            service_name="service",
            version="1.0.0",
            environment="local",
            database_url=" ",
        )


def test_rejects_blank_database_application_name() -> None:
    with pytest.raises(ValueError, match="database_application_name"):
        Settings(
            service_name="service",
            version="1.0.0",
            environment="local",
            database_application_name=" ",
        )


def test_rejects_blank_database_sslrootcert() -> None:
    with pytest.raises(ValueError, match="database_sslrootcert"):
        Settings(
            service_name="service",
            version="1.0.0",
            environment="local",
            database_sslrootcert=" ",
        )


def test_rejects_blank_api_key() -> None:
    with pytest.raises(ValueError, match="api_key"):
        Settings(service_name="service", version="1.0.0", environment="local", api_key=" ")


def test_rejects_blank_service_name() -> None:
    with pytest.raises(ValueError, match="service_name"):
        Settings(service_name=" ", version="1.0.0", environment="local")


def test_rejects_blank_version() -> None:
    with pytest.raises(ValueError, match="version"):
        Settings(service_name="service", version=" ", environment="local")


def test_rejects_non_positive_approval_timeout() -> None:
    with pytest.raises(ValueError, match="approval_timeout_seconds"):
        Settings(
            service_name="service",
            version="1.0.0",
            environment="local",
            approval_timeout_seconds=0,
        )
