"""Application policy for registry metadata and examples."""

from __future__ import annotations

from collections.abc import Mapping

from application.registry.specs import ModuleSpec
from application.validation.types import value_matches_type
from domain.entities.registry import ModuleInput
from domain.errors import RegistryError


class RegistryErrorFactory:
    """Builds structured errors for registry validation."""

    def create_error(
        self,
        *,
        code: str,
        message: str,
        context: Mapping[str, object] | None = None,
        module_name: str | None = None,
    ) -> RegistryError:
        return RegistryError(
            code=code,
            message=message,
            module=module_name or __name__,
            context=context,
        )


class TypeValidator:
    """Validates values against declared registry input types."""

    def __init__(self, error_factory: RegistryErrorFactory | None = None) -> None:
        self._error_factory = error_factory or RegistryErrorFactory()

    def value_matches_type(self, value: object, declared: str) -> bool:
        return value_matches_type(value, declared)

    def validate_example_value(
        self,
        *,
        value: object,
        input_definition: ModuleInput,
        module_name: str,
        example_index: int,
    ) -> None:
        if not self.value_matches_type(value, input_definition.type):
            raise self._error_factory.create_error(
                code="REGISTRY_INVALID_EXAMPLE",
                message="Example value does not match the declared input type",
                context={
                    "module": module_name,
                    "input": input_definition.name,
                    "example_index": example_index,
                },
                module_name=module_name,
            )

    def validate_default(
        self,
        *,
        value: object,
        input_definition: ModuleInput,
        module_name: str,
    ) -> None:
        if not self.value_matches_type(value, input_definition.type):
            raise self._error_factory.create_error(
                code="REGISTRY_INVALID_DEFAULT",
                message="Module default does not match the declared input type",
                context={"module": module_name, "input": input_definition.name},
                module_name=module_name,
            )


class ExampleValidator:
    """Validates module examples against their declared inputs."""

    def __init__(
        self,
        type_validator: TypeValidator | None = None,
        error_factory: RegistryErrorFactory | None = None,
    ) -> None:
        self._type_validator = type_validator or TypeValidator()
        self._error_factory = error_factory or RegistryErrorFactory()

    def validate_examples(
        self,
        *,
        spec: ModuleSpec,
        inputs: tuple[ModuleInput, ...],
    ) -> None:
        by_name = {item.name: item for item in inputs}
        caller_inputs = {item.name for item in inputs if not item.pipeline_input}
        required = {item.name for item in inputs if item.required and not item.pipeline_input}

        for index, example in enumerate(spec.examples):
            unknown = sorted(set(example) - set(by_name))
            if unknown:
                raise self._error_factory.create_error(
                    code="REGISTRY_INVALID_EXAMPLE",
                    message="Example contains unknown inputs",
                    context={
                        "module": spec.name,
                        "example_index": index,
                        "inputs": unknown,
                    },
                    module_name=spec.name,
                )
            pipeline = sorted(set(example) & (set(by_name) - caller_inputs))
            if pipeline:
                raise self._error_factory.create_error(
                    code="REGISTRY_INVALID_EXAMPLE",
                    message="Examples must not supply pipeline-managed inputs",
                    context={
                        "module": spec.name,
                        "example_index": index,
                        "inputs": pipeline,
                    },
                    module_name=spec.name,
                )
            missing = sorted(required - set(example))
            if missing:
                raise self._error_factory.create_error(
                    code="REGISTRY_INVALID_EXAMPLE",
                    message="Example is missing required inputs",
                    context={
                        "module": spec.name,
                        "example_index": index,
                        "inputs": missing,
                    },
                    module_name=spec.name,
                )
            for name, value in example.items():
                self._type_validator.validate_example_value(
                    value=value,
                    input_definition=by_name[name],
                    module_name=spec.name,
                    example_index=index,
                )


__all__ = ["ExampleValidator", "RegistryErrorFactory", "TypeValidator"]
