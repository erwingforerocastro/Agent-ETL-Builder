"""Health use case."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class HealthStatus:
    status: Literal["ok"]
    service: str
    version: str


class GetHealthUseCase:
    def __init__(self, *, service_name: str, version: str) -> None:
        self._service_name = service_name
        self._version = version

    def execute(self) -> HealthStatus:
        return HealthStatus(status="ok", service=self._service_name, version=self._version)
