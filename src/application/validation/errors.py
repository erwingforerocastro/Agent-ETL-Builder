"""Structured errors raised while validating plans."""

from collections.abc import Mapping

from domain.errors import PlanValidationError


class PlanValidationErrorFactory:
    """Builds structured errors for plan validation checks."""

    def __init__(self, module: str = __name__) -> None:
        self._module = module

    def error(
        self,
        *,
        code: str,
        message: str,
        context: Mapping[str, object] | None = None,
    ) -> PlanValidationError:
        return PlanValidationError(
            code=code,
            message=message,
            module=self._module,
            context=context,
        )


__all__ = ["PlanValidationError", "PlanValidationErrorFactory"]
