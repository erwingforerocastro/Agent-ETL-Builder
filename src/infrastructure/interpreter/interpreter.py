"""Plan interpreter - executes validated plans through allowlisted functions."""

from typing import Any

import pandas as pd

from application.ports.module_registry import ModuleRegistryPort
from domain.entities.plan import ExecutionPlan
from infrastructure.sandbox.executor import SandboxExecutor
from infrastructure.sandbox.limits import SandboxLimits


class InterpreterError(Exception):
    pass


class PlanInterpreter:
    def __init__(
        self,
        registry: ModuleRegistryPort,
        sandbox: SandboxExecutor | None = None,
        limits: SandboxLimits | None = None,
    ) -> None:
        self._registry = registry
        self._sandbox = sandbox or SandboxExecutor(limits or SandboxLimits())

    def execute(self, plan: ExecutionPlan) -> dict[str, Any]:
        result: dict[str, Any] = {"status": "success", "outputs": []}
        df: pd.DataFrame | None = None

        # Execute source
        if plan.source is not None:
            func = self._registry.function_for(plan.source.operation)
            try:
                df = self._sandbox.run(func, **plan.source.params)
            except TypeError:
                try:
                    df = self._sandbox.run(func, df, **plan.source.params) if df is not None else self._sandbox.run(func, **plan.source.params)
                except Exception:
                    try:
                        df = self._sandbox.run(func, pd.DataFrame(), **plan.source.params)
                    except Exception:
                        raise


        # Execute transformations
        for step in plan.transformations:
            if df is None:
                raise InterpreterError("No DataFrame available for transformation")
            func = self._registry.function_for(step.operation)
            try:
                df = self._sandbox.run(func, df, **step.params)
            except Exception as exc:
                if plan.on_error == "fail_fast":
                    raise
                # continue on error
                continue

        # Execute destination
        if plan.destination is not None:
            if df is None:
                raise InterpreterError("No DataFrame available for destination")
            func = self._registry.function_for(plan.destination.operation)
            try:
                out = self._sandbox.run(func, df, **plan.destination.params)
                result["outputs"].append(out)
            except Exception:
                if plan.on_error == "fail_fast":
                    raise
        else:
            # assessment mode
            result["dataframe"] = df

        return result
