from application.use_cases.get_health import GetHealthUseCase


def test_execute_returns_healthy_status() -> None:
    use_case = GetHealthUseCase(service_name="test-service", version="1.2.3")

    result = use_case.execute()

    assert result.status == "ok"
    assert result.service == "test-service"
    assert result.version == "1.2.3"
