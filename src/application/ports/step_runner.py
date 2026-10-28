"""Pipeline step execution contract used by the execute-plan use case."""

from collections.abc import Mapping
from typing import Protocol


class StepRunnerPort(Protocol):
    """Runs one validated pipeline step without exposing its data framework."""

    def run_source(self, operation: str, params: Mapping[str, object]) -> object: ...

    def run_transformation(
        self,
        operation: str,
        params: Mapping[str, object],
        data: object,
    ) -> object: ...

    def run_destination(
        self,
        operation: str,
        params: Mapping[str, object],
        data: object,
    ) -> object: ...
