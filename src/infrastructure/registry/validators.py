"""Registry validation logic."""

from __future__ import annotations

import inspect
import types
from collections.abc import Callable, Mapping, Sequence
from importlib.util import find_spec
from typing import Literal, Union, get_args, get_origin, get_type_hints

import pandas as pd

from application.registry.constants import ALLOWED_MODULE_PREFIX, OUTPUT_DESCRIPTION
from application.registry.specs import ModuleSpec
from application.validation.types import value_matches_type
from domain.entities.registry import (
    ModuleInput,
    ModuleMetadata,
    ModuleOutput,
    RegistrySnapshot,
)
from domain.errors import RegistryError


class RegistryValidator:
    """Validates module specifications and signatures."""

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


class SignatureValidator:
    """Validates function signatures and annotations."""

    def __init__(self, error_factory: RegistryValidator | None = None) -> None:
        self._error_factory = error_factory or RegistryValidator()

    def annotation_to_text(self, annotation: object, *, module_name: str, input_name: str) -> str:
        if annotation is pd.DataFrame:
            return "DataFrame"
        if annotation is str:
            return "string"
        if annotation is int:
            return "integer"
        if annotation is float:
            return "number"
        if annotation is bool:
            return "boolean"
        if annotation is type(None):
            return "null"

        origin = get_origin(annotation)
        args = get_args(annotation)
        if origin is Literal:
            return "enum[" + "|".join(str(value) for value in args) + "]"
        if origin in {Union, types.UnionType}:
            rendered = tuple(
                self.annotation_to_text(arg, module_name=module_name, input_name=input_name)
                for arg in args
            )
            if len(rendered) == 2 and "null" in rendered:
                other = rendered[0] if rendered[1] == "null" else rendered[1]
                return f"{other} | null"
            return " | ".join(rendered)
        if origin in {Sequence, list, tuple}:
            item = (
                self.annotation_to_text(args[0], module_name=module_name, input_name=input_name)
                if args
                else "unknown"
            )
            return f"array[{item}]"

        raise self._error_factory.create_error(
            code="REGISTRY_UNSUPPORTED_SIGNATURE",
            message="Module input uses an unsupported type annotation",
            context={
                "module": module_name,
                "input": input_name,
                "annotation": str(annotation),
            },
            module_name=module_name,
        )

    def format_default(self, value: object) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, str):
            return value
        return repr(value)


class TypeValidator:
    """Validates values against declared types."""

    def __init__(self, error_factory: RegistryValidator | None = None) -> None:
        self._error_factory = error_factory or RegistryValidator()

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


class DependencyValidator:
    """Validates module dependencies."""

    def __init__(self, error_factory: RegistryValidator | None = None) -> None:
        self._error_factory = error_factory or RegistryValidator()

    def validate_dependencies(self, spec: ModuleSpec) -> None:
        for dependency in spec.dependencies:
            if find_spec(dependency) is None:
                raise self._error_factory.create_error(
                    code="REGISTRY_MISSING_DEPENDENCY",
                    message="A declared module dependency is unavailable",
                    context={"module": spec.name, "dependency": dependency},
                    module_name=spec.name,
                )


class ExampleValidator:
    """Validates module examples."""

    def __init__(
        self,
        type_validator: TypeValidator | None = None,
        error_factory: RegistryValidator | None = None,
    ) -> None:
        self._type_validator = type_validator or TypeValidator()
        self._error_factory = error_factory or RegistryValidator()

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


class ModuleMetadataBuilder:
    """Builds ModuleMetadata from ModuleSpec."""

    def __init__(
        self,
        signature_validator: SignatureValidator | None = None,
        type_validator: TypeValidator | None = None,
        dependency_validator: DependencyValidator | None = None,
        example_validator: ExampleValidator | None = None,
        error_factory: RegistryValidator | None = None,
    ) -> None:
        self._signature_validator = signature_validator or SignatureValidator()
        self._type_validator = type_validator or TypeValidator()
        self._dependency_validator = dependency_validator or DependencyValidator()
        self._example_validator = example_validator or ExampleValidator()
        self._error_factory = error_factory or RegistryValidator()

    def metadata_for(
        self,
        spec: ModuleSpec,
        function: Callable[..., pd.DataFrame],
    ) -> ModuleMetadata:
        self._dependency_validator.validate_dependencies(spec)
        if spec.name != function.__name__:
            raise self._error_factory.create_error(
                code="REGISTRY_SIGNATURE_MISMATCH",
                message="Registry name does not match the callable name",
                context={"module": spec.name, "function": function.__name__},
                module_name=spec.name,
            )
        module_path = function.__module__
        if not module_path.startswith(ALLOWED_MODULE_PREFIX):
            raise self._error_factory.create_error(
                code="REGISTRY_INVALID_MODULE_PATH",
                message="Module is outside the approved import prefix",
                context={"module": spec.name, "path": module_path},
                module_name=spec.name,
            )

        try:
            signature = inspect.signature(function)
            hints = get_type_hints(function)
        except (NameError, TypeError, ValueError) as exc:
            raise self._error_factory.create_error(
                code="REGISTRY_UNSUPPORTED_SIGNATURE",
                message="Module signature could not be inspected",
                context={"module": spec.name},
                module_name=spec.name,
            ) from exc

        unknown_constraints = sorted(set(spec.constraints) - set(signature.parameters))
        if unknown_constraints:
            raise self._error_factory.create_error(
                code="REGISTRY_INVALID_CONSTRAINT",
                message="Constraints reference unknown inputs",
                context={"module": spec.name, "inputs": unknown_constraints},
                module_name=spec.name,
            )

        inputs: list[ModuleInput] = []
        for parameter in signature.parameters.values():
            if parameter.kind in {
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            }:
                raise self._error_factory.create_error(
                    code="REGISTRY_UNSUPPORTED_SIGNATURE",
                    message="Modules may not use positional-only or variadic parameters",
                    context={"module": spec.name, "input": parameter.name},
                    module_name=spec.name,
                )
            annotation = hints.get(parameter.name, parameter.annotation)
            if annotation is inspect.Parameter.empty:
                raise self._error_factory.create_error(
                    code="REGISTRY_UNSUPPORTED_SIGNATURE",
                    message="Every module input must be annotated",
                    context={"module": spec.name, "input": parameter.name},
                    module_name=spec.name,
                )
            pipeline_input = annotation is pd.DataFrame
            if not pipeline_input and parameter.kind is not inspect.Parameter.KEYWORD_ONLY:
                raise self._error_factory.create_error(
                    code="REGISTRY_SIGNATURE_MISMATCH",
                    message="Module parameters after the pipeline input must be keyword-only",
                    context={"module": spec.name, "input": parameter.name},
                    module_name=spec.name,
                )
            has_default = parameter.default is not inspect.Parameter.empty
            input_definition = ModuleInput(
                name=parameter.name,
                type=self._signature_validator.annotation_to_text(
                    annotation,
                    module_name=spec.name,
                    input_name=parameter.name,
                ),
                required=not has_default,
                default=self._signature_validator.format_default(parameter.default)
                if has_default
                else None,
                constraints=spec.constraints.get(parameter.name, ()),
                pipeline_input=pipeline_input,
            )
            if has_default and not pipeline_input:
                self._type_validator.validate_default(
                    value=parameter.default,
                    input_definition=input_definition,
                    module_name=spec.name,
                )
            inputs.append(input_definition)

        if hints.get("return") is not pd.DataFrame:
            raise self._error_factory.create_error(
                code="REGISTRY_SIGNATURE_MISMATCH",
                message="Module return annotation must be DataFrame",
                context={"module": spec.name},
                module_name=spec.name,
            )

        self._example_validator.validate_examples(spec=spec, inputs=tuple(inputs))
        return ModuleMetadata(
            name=spec.name,
            version=spec.version,
            module=module_path,
            function=function.__name__,
            description=spec.description,
            inputs=tuple(inputs),
            output=ModuleOutput(type="DataFrame", description=OUTPUT_DESCRIPTION),
            dependencies=spec.dependencies,
            side_effects=spec.side_effects,
            examples=spec.examples,
            supports_chunking=spec.supports_chunking,
            idempotent=spec.idempotent,
            supported_dialects=spec.supported_dialects,
            security_notes=spec.security_notes,
        )


class RegistrySnapshotBuilder:
    """Builds registry snapshots."""

    def __init__(self, metadata_builder: ModuleMetadataBuilder | None = None) -> None:
        self._metadata_builder = metadata_builder or ModuleMetadataBuilder()

    def build_snapshot(
        self,
        specs: Sequence[ModuleSpec],
        functions: Mapping[str, Callable[..., pd.DataFrame]],
        registry_version: str = "1.0.0",
    ) -> RegistrySnapshot:
        names = [spec.name for spec in specs]
        error_factory = RegistryValidator()
        if len(names) != len(set(names)):
            duplicates = sorted({name for name in names if names.count(name) > 1})
            raise error_factory.create_error(
                code="REGISTRY_DUPLICATE_MODULE",
                message="Registry contains duplicate module names",
                context={"modules": duplicates},
                module_name=__name__,
            )

        missing = sorted(set(names) - set(functions))
        if missing:
            raise error_factory.create_error(
                code="REGISTRY_MISSING_FUNCTION",
                message="Registry spec has no bound callable",
                context={"modules": missing},
                module_name=__name__,
            )
        unknown = sorted(set(functions) - set(names))
        if unknown:
            raise error_factory.create_error(
                code="REGISTRY_UNKNOWN_FUNCTION",
                message="Registry contains a callable without a spec",
                context={"modules": unknown},
                module_name=__name__,
            )

        modules = tuple(
            self._metadata_builder.metadata_for(spec, functions[spec.name]) for spec in specs
        )
        return RegistrySnapshot(version=registry_version, modules=modules)


# Backward compatible function aliases
def _registry_error(
    *,
    code: str,
    message: str,
    context: Mapping[str, object] | None = None,
) -> RegistryError:
    factory = RegistryValidator()
    return factory.create_error(code=code, message=message, context=context)


def _annotation_to_text(annotation: object, *, module_name: str, input_name: str) -> str:
    validator = SignatureValidator()
    return validator.annotation_to_text(annotation, module_name=module_name, input_name=input_name)


def _format_default(value: object) -> str:
    validator = SignatureValidator()
    return validator.format_default(value)


def _validate_example_value(
    *,
    value: object,
    input_definition: ModuleInput,
    module_name: str,
    example_index: int,
) -> None:
    validator = TypeValidator()
    validator.validate_example_value(
        value=value,
        input_definition=input_definition,
        module_name=module_name,
        example_index=example_index,
    )


def _value_matches_type(value: object, declared: str) -> bool:
    validator = TypeValidator()
    return validator.value_matches_type(value, declared)


def _validate_default(
    *,
    value: object,
    input_definition: ModuleInput,
    module_name: str,
) -> None:
    validator = TypeValidator()
    validator.validate_default(
        value=value,
        input_definition=input_definition,
        module_name=module_name,
    )


def _validate_dependencies(spec: ModuleSpec) -> None:
    validator = DependencyValidator()
    validator.validate_dependencies(spec)


def _validate_examples(
    *,
    spec: ModuleSpec,
    inputs: tuple[ModuleInput, ...],
) -> None:
    validator = ExampleValidator()
    validator.validate_examples(spec=spec, inputs=tuple(inputs))


def _metadata_for(
    spec: ModuleSpec,
    function: Callable[..., pd.DataFrame],
) -> ModuleMetadata:
    builder = ModuleMetadataBuilder()
    return builder.metadata_for(spec, function)
