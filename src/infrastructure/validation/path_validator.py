"""Workspace path validation for plan arguments."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import PurePosixPath

from domain.entities.plan import ExecutionPlan
from domain.entities.registry import ModuleInput
from infrastructure.validation.constants import (
    DRIVE_PREFIX,
    PATH_KEYS,
    PATH_SUFFIXES,
    WINDOWS_RESERVED_NAME,
)
from infrastructure.validation.errors import PlanValidationErrorFactory
from infrastructure.validation.operations import OperationPolicy, iter_operations
from infrastructure.validation.settings import PlanValidationSettings


class PathValueValidator:
    """Validates individual path values against workspace confinement rules."""

    def __init__(
        self,
        settings: PlanValidationSettings,
        error_factory: PlanValidationErrorFactory | None = None,
    ) -> None:
        self._settings = settings
        self._error_factory = error_factory or PlanValidationErrorFactory()

    def validate(self, value: object, *, label: str) -> None:
        if value is None:
            return
        if isinstance(value, str):
            self._validate_single_path(value, label=label)
            return
        if isinstance(value, list | tuple):
            for index, item in enumerate(value):
                if not isinstance(item, str):
                    raise self._error_factory.error(
                        code="PLAN_INVALID_PATH",
                        message="Path values must be strings",
                        context={"step": label, "index": index},
                    )
                self._validate_single_path(item, label=f"{label}[{index}]")
            return
        raise self._error_factory.error(
            code="PLAN_INVALID_PATH",
            message="Path values must be a string or a list of strings",
            context={"step": label},
        )

    def _validate_single_path(self, value: str, *, label: str) -> None:
        if not value.strip():
            raise self._error_factory.error(
                code="PLAN_INVALID_PATH",
                message="Path must be a non-empty string",
                context={"step": label},
            )
        if len(value) > self._settings.max_path_length:
            raise self._error_factory.error(
                code="PLAN_PATH_TOO_LONG",
                message="Path exceeds the maximum length",
                context={"step": label, "length": len(value)},
            )
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise self._error_factory.error(
                code="PLAN_INVALID_PATH",
                message="Path must not contain control characters",
                context={"step": label},
            )
        if "://" in value:
            raise self._error_factory.error(
                code="PLAN_INVALID_PATH",
                message="URLs are not valid workspace paths",
                context={"step": label},
            )

        normalized = value.replace("\\", "/")
        if (
            normalized.startswith("/")
            or value.startswith("~")
            or DRIVE_PREFIX.match(value)
            or value.startswith("\\\\")
        ):
            raise self._error_factory.error(
                code="PLAN_PATH_NOT_ALLOWED",
                message="Absolute paths are not allowed",
                context={"step": label, "path": value},
            )

        parts = PurePosixPath(normalized).parts
        if not parts:
            raise self._error_factory.error(
                code="PLAN_INVALID_PATH",
                message="Path must name a file or directory",
                context={"step": label, "path": value},
            )
        if ".." in parts:
            raise self._error_factory.error(
                code="PLAN_PATH_TRAVERSAL",
                message="Path traversal is not allowed",
                context={"step": label, "path": value},
            )
        for part in parts:
            if part.endswith(".") or part.endswith(" "):
                raise self._error_factory.error(
                    code="PLAN_PATH_RESERVED_NAME",
                    message="Path contains a Windows-reserved trailing dot or space",
                    context={"step": label, "path": value},
                )
            if ":" in part:
                raise self._error_factory.error(
                    code="PLAN_PATH_NOT_ALLOWED",
                    message="Path must not contain drive or stream separators",
                    context={"step": label, "path": value},
                )
            if WINDOWS_RESERVED_NAME.fullmatch(part):
                raise self._error_factory.error(
                    code="PLAN_PATH_RESERVED_NAME",
                    message="Path contains a Windows-reserved name",
                    context={"step": label, "path": value},
                )
            if len(part) > 255:
                raise self._error_factory.error(
                    code="PLAN_PATH_TOO_LONG",
                    message="Path component exceeds the maximum length",
                    context={"step": label, "path": value},
                )

        workspace_root = self._settings.workspace_root
        candidate = workspace_root.joinpath(*parts)
        try:
            resolved = candidate.resolve(strict=False)
        except OSError as exc:
            raise self._error_factory.error(
                code="PLAN_INVALID_PATH",
                message="Path could not be resolved",
                context={"step": label},
            ) from exc

        try:
            common = os.path.commonpath([str(workspace_root), str(resolved)])
        except ValueError as exc:
            raise self._error_factory.error(
                code="PLAN_PATH_OUTSIDE_WORKSPACE",
                message="Path must be within the workspace",
                context={"step": label, "path": value},
            ) from exc
        if os.path.normcase(common) != os.path.normcase(str(workspace_root)):
            raise self._error_factory.error(
                code="PLAN_PATH_OUTSIDE_WORKSPACE",
                message="Path must be within the workspace",
                context={"step": label, "path": value},
            )
        if len(str(resolved)) > self._settings.max_path_length:
            raise self._error_factory.error(
                code="PLAN_PATH_TOO_LONG",
                message="Resolved path exceeds the maximum length",
                context={"step": label},
            )

        current = workspace_root
        for part in parts:
            current = current / part
            try:
                if current.is_symlink():
                    raise self._error_factory.error(
                        code="PLAN_PATH_SYMLINK",
                        message="Symlinks are not allowed",
                        context={"step": label, "path": value},
                    )
                if not current.exists():
                    break
            except OSError as exc:
                raise self._error_factory.error(
                    code="PLAN_INVALID_PATH",
                    message="Path could not be inspected",
                    context={"step": label},
                ) from exc


class PlanPathValidator:
    """Finds path-like arguments anywhere in a plan and validates them."""

    def __init__(
        self,
        policy: OperationPolicy,
        path_validator: PathValueValidator,
    ) -> None:
        self._policy = policy
        self._path_validator = path_validator

    def validate(self, plan: ExecutionPlan) -> None:
        for call in iter_operations(plan):
            metadata = self._policy.metadata(call.operation)
            for name, value in call.params.items():
                definition = metadata.input(name)
                label = f"{call.label}.{name}"
                if self._is_path_input(name, definition):
                    self._path_validator.validate(value, label=label)
                else:
                    self._scan_nested_paths(value, label=label)

    @staticmethod
    def _is_path_input(name: str, definition: ModuleInput | None) -> bool:
        if definition is not None and any(
            "path" in constraint.lower() for constraint in definition.constraints
        ):
            return True
        return _is_path_key(name)

    def _scan_nested_paths(self, value: object, *, label: str) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                if isinstance(key, str) and _is_path_key(key):
                    self._path_validator.validate(item, label=f"{label}.{key}")
                else:
                    self._scan_nested_paths(item, label=f"{label}.{key}")
        elif isinstance(value, list | tuple):
            for index, item in enumerate(value):
                self._scan_nested_paths(item, label=f"{label}[{index}]")


def _is_path_key(key: str) -> bool:
    lower = key.lower()
    return lower in PATH_KEYS or lower.endswith(PATH_SUFFIXES)
