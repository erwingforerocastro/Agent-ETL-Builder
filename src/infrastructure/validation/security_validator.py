"""Security scanning of plan argument values."""

from __future__ import annotations

import math
from collections.abc import Mapping

from domain.entities.plan import ExecutionPlan
from infrastructure.validation.constants import (
    DANGEROUS_PATTERNS,
    FORBIDDEN_PARAM_KEYS,
    SECRET_PARAM_KEYS,
    SQL_PATTERNS,
)
from infrastructure.validation.errors import PlanValidationErrorFactory
from infrastructure.validation.operations import iter_operations
from infrastructure.validation.settings import PlanValidationSettings


class SecurityValidator:
    """Rejects code, raw SQL, credentials, and unsafe value shapes in params."""

    def __init__(
        self,
        settings: PlanValidationSettings,
        error_factory: PlanValidationErrorFactory | None = None,
    ) -> None:
        self._settings = settings
        self._error_factory = error_factory or PlanValidationErrorFactory()

    def validate(self, plan: ExecutionPlan) -> None:
        for call in iter_operations(plan):
            self._walk_params(call.params, path=call.label)

    def _walk_params(self, value: object, *, path: str, depth: int = 0) -> None:
        if depth > self._settings.max_param_depth:
            raise self._error_factory.error(
                code="PLAN_INVALID_ARGUMENT",
                message="Plan arguments exceed the maximum nesting depth",
                context={"path": path},
            )
        if isinstance(value, str):
            if len(value) > self._settings.max_string_length:
                raise self._error_factory.error(
                    code="PLAN_INVALID_ARGUMENT",
                    message="Plan argument exceeds the maximum string length",
                    context={"path": path},
                )
            self._check_string(value, path=path)
            return
        if value is None or isinstance(value, bool):
            return
        if isinstance(value, int):
            return
        if isinstance(value, float):
            if not math.isfinite(value):
                raise self._error_factory.error(
                    code="PLAN_INVALID_ARGUMENT",
                    message="Plan arguments must not contain NaN or infinity",
                    context={"path": path},
                )
            return
        if isinstance(value, Mapping):
            for key, item in value.items():
                if not isinstance(key, str):
                    raise self._error_factory.error(
                        code="PLAN_INVALID_ARGUMENT",
                        message="Plan argument names must be strings",
                        context={"path": path},
                    )
                lower = key.lower()
                if lower in FORBIDDEN_PARAM_KEYS:
                    raise self._error_factory.error(
                        code="PLAN_UNSAFE_CONTENT",
                        message="Plan arguments must not contain code or raw SQL",
                        context={"path": path, "argument": key},
                    )
                if lower in SECRET_PARAM_KEYS and item not in (None, ""):
                    raise self._error_factory.error(
                        code="PLAN_SECRET_IN_PARAMS",
                        message="Credentials must not be embedded in plans",
                        context={"path": path, "argument": key},
                    )
                self._walk_params(item, path=f"{path}.{key}", depth=depth + 1)
            return
        if isinstance(value, list | tuple):
            for index, item in enumerate(value):
                self._walk_params(item, path=f"{path}[{index}]", depth=depth + 1)
            return
        raise self._error_factory.error(
            code="PLAN_INVALID_ARGUMENT",
            message="Plan arguments contain an unsupported value type",
            context={"path": path, "value_type": type(value).__name__},
        )

    def _check_string(self, value: str, *, path: str) -> None:
        for pattern in DANGEROUS_PATTERNS:
            if pattern.search(value):
                raise self._error_factory.error(
                    code="PLAN_UNSAFE_CONTENT",
                    message="Plan argument contains code execution syntax",
                    context={"path": path},
                )
        for pattern in SQL_PATTERNS:
            if pattern.search(value):
                raise self._error_factory.error(
                    code="PLAN_UNSAFE_CONTENT",
                    message="Plan argument contains raw SQL",
                    context={"path": path},
                )
