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
    monkeypatch.delenv("AGENT_ETL_API_KEY", raising=False)

    settings = Settings.from_env()

    assert settings.service_name == "agent-etl-builder"
    assert settings.version == version("agent-etl-builder")
    assert settings.environment == "local"
    assert settings.approval_timeout_seconds == 300
    assert settings.cleanup_policy is CleanupPolicy.CLEANUP
    assert settings.max_request_bytes == 1_000_000
    assert settings.api_key is None


def test_from_env_reads_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_ETL_SERVICE_NAME", "custom-service")
    monkeypatch.setenv("AGENT_ETL_ENVIRONMENT", "TEST")
    monkeypatch.setenv("AGENT_ETL_APPROVAL_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("AGENT_ETL_CLEANUP_POLICY", "RETAIN")
    monkeypatch.setenv("AGENT_ETL_MAX_REQUEST_BYTES", "2048")
    monkeypatch.setenv("AGENT_ETL_API_KEY", "secret-key")

    settings = Settings.from_env()

    assert settings.service_name == "custom-service"
    assert settings.environment == "test"
    assert settings.approval_timeout_seconds == 12.5
    assert settings.cleanup_policy is CleanupPolicy.RETAIN
    assert settings.max_request_bytes == 2048
    assert settings.api_key == "secret-key"


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
