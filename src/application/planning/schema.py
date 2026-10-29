"""Registry-derived JSON schema for natural-language plan drafts."""

from __future__ import annotations

from domain.entities.registry import ModuleInput, ModuleMetadata, RegistrySnapshot

MAX_DRAFT_TRANSFORMATIONS = 20


def _is_transformation(module: ModuleMetadata) -> bool:
    return any(item.pipeline_input for item in module.inputs) and not module.side_effects


def _type_schema(declared: str) -> dict[str, object]:
    alternatives = [item.strip() for item in declared.split(" | ") if item.strip()]
    schemas = [_single_type_schema(item) for item in alternatives]
    if not schemas:
        return {}
    if len(schemas) == 1:
        return schemas[0]
    return {"anyOf": schemas}


def _single_type_schema(declared: str) -> dict[str, object]:
    if declared == "string":
        return {"type": "string"}
    if declared == "integer":
        return {"type": "integer"}
    if declared == "number":
        return {"type": "number"}
    if declared == "boolean":
        return {"type": "boolean"}
    if declared == "null":
        return {"type": "null"}
    if declared.startswith("enum[") and declared.endswith("]"):
        return {"type": "string", "enum": declared[5:-1].split("|")}
    if declared.startswith("array[") and declared.endswith("]"):
        return {
            "type": "array",
            "items": _type_schema(declared[6:-1]),
        }
    return {}


def _parameter_schema(item: ModuleInput) -> dict[str, object]:
    return _type_schema(item.type)


def _operation_schema(module: ModuleMetadata) -> dict[str, object]:
    properties: dict[str, object] = {}
    required: list[str] = []
    for item in module.inputs:
        if item.pipeline_input:
            continue
        properties[item.name] = _parameter_schema(item)
        if item.required:
            required.append(item.name)
    return {
        "type": "object",
        "properties": {
            "operation": {"type": "string", "enum": [module.name]},
            "params": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
        "required": ["operation", "params"],
        "additionalProperties": False,
    }


def build_plan_draft_schema(
    snapshot: RegistrySnapshot,
    *,
    max_transformations: int = MAX_DRAFT_TRANSFORMATIONS,
) -> dict[str, object]:
    """Build a strict JSON schema for the transformation portion of a plan."""
    operations = [
        _operation_schema(module) for module in snapshot.modules if _is_transformation(module)
    ]
    if not operations:
        raise ValueError("registry has no transformation modules")
    if max_transformations <= 0:
        raise ValueError("max_transformations must be positive")
    return {
        "type": "object",
        "properties": {
            "name": {"type": "string", "minLength": 1, "maxLength": 200},
            "description": {"type": "string", "minLength": 1, "maxLength": 2_000},
            "transformations": {
                "type": "array",
                "items": {"oneOf": operations},
                "maxItems": max_transformations,
            },
            "questions": {
                "type": "array",
                "items": {"type": "string", "minLength": 1, "maxLength": 500},
                "maxItems": 10,
            },
            "missing_inputs": {
                "type": "array",
                "items": {"type": "string", "minLength": 1, "maxLength": 100},
                "maxItems": 10,
            },
        },
        "required": [
            "name",
            "description",
            "transformations",
            "questions",
            "missing_inputs",
        ],
        "additionalProperties": False,
    }


__all__ = ["MAX_DRAFT_TRANSFORMATIONS", "build_plan_draft_schema"]
