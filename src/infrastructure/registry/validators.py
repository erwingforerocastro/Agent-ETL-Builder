"""Registry metadata validation."""

from __future__ import annotations

import inspect
import types
from collections.abc import Callable, Mapping, Sequence
from importlib.util import find_spec
from typing import Literal, Union, get_args, get_origin, get_type_hints

import pandas as pd

from application.registry.constants import OUTPUT_DESCRIPTION
from application.registry.metadata import RegistryErrorFactory
from application.registry.specs import ModuleSpec
from application.validation.types import value_matches_type
from domain.entities.registry import ModuleInput, ModuleMetadata, ModuleOutput
from infrastructure.registry.bindings import ALLOWED_MODULE_PREFIX, CAPABILITY_PACKAGES


class ModuleMetadataBuilder:
    """Builds validated ModuleMetadata from a spec and its callable."""

    def __init__(self, error_factory: RegistryErrorFactory | None = None) -> None:
        self._error_factory = error_factory or RegistryErrorFactory()

    def metadata_for(
        self,
        spec: ModuleSpec,
        function: Callable[..., pd.DataFrame],
    ) -> ModuleMetadata:
        self._validate_dependencies(spec)
        self._validate_name_and_module(spec, function)
        signature, hints = self._inspect_signature(spec, function)
        self._reject_unknown_constraints(spec, signature)
        inputs = self._build_inputs(spec, signature, hints)
        self._validate_return_annotation(spec, hints)
        self._validate_examples(spec, inputs)
        return self._metadata(spec, function, inputs)

    def _validate_dependencies(self, spec: ModuleSpec) -> None:
        for dependency in spec.dependencies:
            package = CAPABILITY_PACKAGES.get(dependency, dependency)
            if find_spec(package) is None:
                raise self._error_factory.create_error(
                    code="REGISTRY_MISSING_DEPENDENCY",
                    message="A declared module dependency is unavailable",
                    context={"module": spec.name, "dependency": dependency},
                    module_name=spec.name,
                )

    def _validate_name_and_module(
        self,
        spec: ModuleSpec,
        function: Callable[..., pd.DataFrame],
    ) -> None:
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

    def _inspect_signature(
        self,
        spec: ModuleSpec,
        function: Callable[..., pd.DataFrame],
    ) -> tuple[inspect.Signature, Mapping[str, object]]:
        try:
            return inspect.signature(function), get_type_hints(function)
        except (NameError, TypeError, ValueError) as exc:
            raise self._error_factory.create_error(
                code="REGISTRY_UNSUPPORTED_SIGNATURE",
                message="Module signature could not be inspected",
                context={"module": spec.name},
                module_name=spec.name,
            ) from exc

    def _reject_unknown_constraints(
        self,
        spec: ModuleSpec,
        signature: inspect.Signature,
    ) -> None:
        unknown = sorted(set(spec.constraints) - set(signature.parameters))
        if unknown:
            raise self._error_factory.create_error(
                code="REGISTRY_INVALID_CONSTRAINT",
                message="Constraints reference unknown inputs",
                context={"module": spec.name, "inputs": unknown},
                module_name=spec.name,
            )

    def _build_inputs(
        self,
        spec: ModuleSpec,
        signature: inspect.Signature,
        hints: Mapping[str, object],
    ) -> tuple[ModuleInput, ...]:
        inputs: list[ModuleInput] = []
        for parameter in signature.parameters.values():
            self._reject_unsupported_parameter(spec, parameter)
            input_definition = self._input_for(spec, parameter, hints)
            inputs.append(input_definition)
        return tuple(inputs)

    def _reject_unsupported_parameter(
        self,
        spec: ModuleSpec,
        parameter: inspect.Parameter,
    ) -> None:
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

    def _input_for(
        self,
        spec: ModuleSpec,
        parameter: inspect.Parameter,
        hints: Mapping[str, object],
    ) -> ModuleInput:
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
        definition = ModuleInput(
            name=parameter.name,
            type=self._annotation_to_text(
                annotation,
                module_name=spec.name,
                input_name=parameter.name,
            ),
            required=not has_default,
            default=self._format_default(parameter.default) if has_default else None,
            constraints=spec.constraints.get(parameter.name, ()),
            pipeline_input=pipeline_input,
        )
        if has_default and not pipeline_input:
            self._validate_default(
                value=parameter.default,
                input_definition=definition,
                module_name=spec.name,
            )
        return definition

    def _validate_return_annotation(
        self,
        spec: ModuleSpec,
        hints: Mapping[str, object],
    ) -> None:
        if hints.get("return") is not pd.DataFrame:
            raise self._error_factory.create_error(
                code="REGISTRY_SIGNATURE_MISMATCH",
                message="Module return annotation must be DataFrame",
                context={"module": spec.name},
                module_name=spec.name,
            )

    def _validate_examples(
        self,
        spec: ModuleSpec,
        inputs: tuple[ModuleInput, ...],
    ) -> None:
        by_name = {item.name: item for item in inputs}
        caller_inputs = {item.name for item in inputs if not item.pipeline_input}
        required = {item.name for item in inputs if item.required and not item.pipeline_input}

        for index, example in enumerate(spec.examples):
            self._validate_example(
                spec,
                example,
                index=index,
                by_name=by_name,
                caller_inputs=caller_inputs,
                required=required,
            )

    def _validate_example(
        self,
        spec: ModuleSpec,
        example: Mapping[str, object],
        *,
        index: int,
        by_name: Mapping[str, ModuleInput],
        caller_inputs: set[str],
        required: set[str],
    ) -> None:
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
            self._validate_example_value(
                value=value,
                input_definition=by_name[name],
                module_name=spec.name,
                example_index=index,
            )

    def _validate_example_value(
        self,
        *,
        value: object,
        input_definition: ModuleInput,
        module_name: str,
        example_index: int,
    ) -> None:
        if not value_matches_type(value, input_definition.type):
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

    def _validate_default(
        self,
        *,
        value: object,
        input_definition: ModuleInput,
        module_name: str,
    ) -> None:
        if not value_matches_type(value, input_definition.type):
            raise self._error_factory.create_error(
                code="REGISTRY_INVALID_DEFAULT",
                message="Module default does not match the declared input type",
                context={"module": module_name, "input": input_definition.name},
                module_name=module_name,
            )

    def _annotation_to_text(
        self,
        annotation: object,
        *,
        module_name: str,
        input_name: str,
    ) -> str:
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
                self._annotation_to_text(arg, module_name=module_name, input_name=input_name)
                for arg in args
            )
            if len(rendered) == 2 and "null" in rendered:
                other = rendered[0] if rendered[1] == "null" else rendered[1]
                return f"{other} | null"
            return " | ".join(rendered)
        if origin in {Sequence, list, tuple}:
            item = (
                self._annotation_to_text(
                    args[0],
                    module_name=module_name,
                    input_name=input_name,
                )
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

    @staticmethod
    def _format_default(value: object) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, str):
            return value
        return repr(value)

    def _metadata(
        self,
        spec: ModuleSpec,
        function: Callable[..., pd.DataFrame],
        inputs: tuple[ModuleInput, ...],
    ) -> ModuleMetadata:
        return ModuleMetadata(
            name=spec.name,
            version=spec.version,
            module=function.__module__,
            function=function.__name__,
            description=spec.description,
            inputs=inputs,
            output=ModuleOutput(type="DataFrame", description=OUTPUT_DESCRIPTION),
            dependencies=spec.dependencies,
            side_effects=spec.side_effects,
            examples=spec.examples,
            supports_chunking=spec.supports_chunking,
            idempotent=spec.idempotent,
            supported_dialects=spec.supported_dialects,
            security_notes=spec.security_notes,
        )


__all__ = ["ModuleMetadataBuilder"]
