"""Versioned module registry entities."""

from collections.abc import Mapping
from dataclasses import dataclass


def _require_text(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must not be blank")


@dataclass(frozen=True, slots=True)
class ModuleInput:
    name: str
    type: str
    required: bool
    default: str | None = None
    constraints: tuple[str, ...] = ()
    pipeline_input: bool = False

    def __post_init__(self) -> None:
        _require_text(self.name, "input name")
        _require_text(self.type, "input type")
        if self.pipeline_input and not self.required:
            raise ValueError("pipeline inputs must be required")
        if any(not constraint.strip() for constraint in self.constraints):
            raise ValueError("input constraints must not be blank")


@dataclass(frozen=True, slots=True)
class ModuleOutput:
    type: str
    description: str

    def __post_init__(self) -> None:
        _require_text(self.type, "output type")
        _require_text(self.description, "output description")


@dataclass(frozen=True, slots=True)
class ModuleMetadata:
    name: str
    version: str
    module: str
    function: str
    description: str
    inputs: tuple[ModuleInput, ...]
    output: ModuleOutput
    dependencies: tuple[str, ...]
    side_effects: tuple[str, ...]
    examples: tuple[Mapping[str, object], ...]
    supports_chunking: bool
    idempotent: bool
    supported_dialects: tuple[str, ...]
    security_notes: str

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.name, "module name"),
            (self.version, "module version"),
            (self.module, "module path"),
            (self.function, "function name"),
            (self.description, "module description"),
            (self.security_notes, "security notes"),
        ):
            _require_text(value, field_name)
        input_names = [item.name for item in self.inputs]
        if len(input_names) != len(set(input_names)):
            raise ValueError("module input names must be unique")
        if len(self.dependencies) != len(set(self.dependencies)):
            raise ValueError("module dependencies must be unique")

    def input(self, name: str) -> ModuleInput | None:
        return next((item for item in self.inputs if item.name == name), None)


@dataclass(frozen=True, slots=True)
class RegistrySnapshot:
    version: str
    modules: tuple[ModuleMetadata, ...]

    def __post_init__(self) -> None:
        _require_text(self.version, "registry version")
        names = [module.name for module in self.modules]
        if len(names) != len(set(names)):
            raise ValueError("registry module names must be unique")

    def get(self, name: str) -> ModuleMetadata | None:
        return next((module for module in self.modules if module.name == name), None)
