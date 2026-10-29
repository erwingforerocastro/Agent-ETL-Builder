"""Pandas and sandbox implementation of the step runner port."""

from collections.abc import Mapping

import pandas as pd

from application.ports.module_registry import ModuleRegistryPort
from application.ports.sandbox import SandboxRunnerPort


class RegistryStepRunner:
    """Runs registry functions through the sandbox with DataFrame plumbing."""

    def __init__(
        self,
        registry: ModuleRegistryPort,
        sandbox: SandboxRunnerPort,
    ) -> None:
        self._registry = registry
        self._sandbox = sandbox

    def run_source(self, operation: str, params: Mapping[str, object]) -> object:
        function = self._registry.function_for(operation)
        metadata = self._registry.require(operation)
        if any(item.pipeline_input for item in metadata.inputs):
            return self._sandbox.run(function, pd.DataFrame(), **params)
        return self._sandbox.run(function, **params)

    def run_transformation(
        self,
        operation: str,
        params: Mapping[str, object],
        data: object,
    ) -> object:
        function = self._registry.function_for(operation)
        return self._sandbox.run(function, data, **params)

    def run_destination(
        self,
        operation: str,
        params: Mapping[str, object],
        data: object,
    ) -> object:
        function = self._registry.function_for(operation)
        return self._sandbox.run(function, data, **params)


__all__ = ["RegistryStepRunner"]
