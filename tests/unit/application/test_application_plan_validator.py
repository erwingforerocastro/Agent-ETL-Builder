"""Unit tests proving plan validation policy runs without infrastructure."""

from collections.abc import Callable, Sequence
from typing import Any

import pytest

from application.ports.workspace import WorkspacePathError, WorkspacePathInfo
from application.validation.plan_validator import PlanValidator
from domain.entities.plan import (
    ExecutionPlan,
    PlanChunking,
    PlanSource,
)
from domain.entities.registry import (
    ModuleInput,
    ModuleMetadata,
    ModuleOutput,
    RegistrySnapshot,
)
from domain.errors import PlanValidationError


class _StubRegistry:
    def __init__(self, module: ModuleMetadata) -> None:
        self._module = module

    def snapshot(self) -> RegistrySnapshot:
        return RegistrySnapshot(version="1.0.0", modules=(self._module,))

    def get(self, name: str, *, version: str | None = None) -> ModuleMetadata | None:
        return self._module if name == self._module.name else None

    def require(self, name: str, *, version: str | None = None) -> ModuleMetadata:
        module = self.get(name, version=version)
        if module is None:
            raise AssertionError(f"Unknown module: {name}")
        return module

    def function_for(self, name: str, *, version: str | None = None) -> Callable[..., Any]:
        self.require(name, version=version)
        return lambda: None

    def ensure_version(self, expected_version: str) -> None:
        assert expected_version == "1.0.0"


class _StubWorkspace:
    def __init__(self, info: WorkspacePathInfo) -> None:
        self._info = info

    def inspect(self, parts: Sequence[str]) -> WorkspacePathInfo:
        return self._info


def _module(*inputs: ModuleInput) -> ModuleMetadata:
    return ModuleMetadata(
        name="test_module",
        version="1.0.0",
        module="tests.fake",
        function="test_module",
        description="Test module.",
        inputs=tuple(inputs),
        output=ModuleOutput(type="DataFrame", description="DataFrame"),
        dependencies=("pandas",),
        side_effects=(),
        examples=(),
        supports_chunking=False,
        idempotent=True,
        supported_dialects=(),
        security_notes="Test only.",
    )


def _plan(*, source: PlanSource | None = None) -> ExecutionPlan:
    return ExecutionPlan(
        plan_version="1.0",
        mode="assessment",
        run_id="1729850000000-a1b2c3d4",
        name="test_plan",
        description="A test plan",
        source=source or PlanSource(operation="test_module", params={}),
        transformations=(),
        destination=None,
        chunking=PlanChunking(enabled=True, size=1000),
        on_error="fail_fast",
        approval_required=False,
    )


def test_application_validator_uses_injected_workspace_probe() -> None:
    module = _module()
    validator = PlanValidator(
        _StubRegistry(module),
        workspace=_StubWorkspace(WorkspacePathInfo(resolved="input.csv")),
    )

    validator.validate(_plan())


def test_application_validator_rejects_path_outside_workspace() -> None:
    module = _module(ModuleInput(name="path", type="string", required=True))
    validator = PlanValidator(
        _StubRegistry(module),
        workspace=_StubWorkspace(
            WorkspacePathInfo(
                resolved="outside.csv",
                error=WorkspacePathError.OUTSIDE_WORKSPACE,
            )
        ),
    )
    plan = _plan(source=PlanSource(operation="test_module", params={"path": "outside.csv"}))

    with pytest.raises(PlanValidationError) as caught:
        validator.validate(plan)

    assert caught.value.code == "PLAN_PATH_OUTSIDE_WORKSPACE"
