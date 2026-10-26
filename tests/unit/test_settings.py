from importlib.metadata import PackageNotFoundError, version

import pytest

from infrastructure.config import settings as settings_module
from infrastructure.config.settings import Settings


def test_from_env_uses_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENT_ETL_SERVICE_NAME", raising=False)
    monkeypatch.delenv("AGENT_ETL_ENVIRONMENT", raising=False)

    settings = Settings.from_env()

    assert settings.service_name == "agent-etl-builder"
    assert settings.version == version("agent-etl-builder")
    assert settings.environment == "local"


def test_from_env_reads_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_ETL_SERVICE_NAME", "custom-service")
    monkeypatch.setenv("AGENT_ETL_ENVIRONMENT", "TEST")

    settings = Settings.from_env()

    assert settings.service_name == "custom-service"
    assert settings.environment == "test"


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


def test_rejects_blank_service_name() -> None:
    with pytest.raises(ValueError, match="service_name"):
        Settings(service_name=" ", version="1.0.0", environment="local")


def test_rejects_blank_version() -> None:
    with pytest.raises(ValueError, match="version"):
        Settings(service_name="service", version=" ", environment="local")
