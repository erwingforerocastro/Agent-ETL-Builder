"""Backward-compatible exports for plan validation errors."""

from application.validation.errors import PlanValidationErrorFactory
from domain.errors import PlanValidationError

__all__ = ["PlanValidationError", "PlanValidationErrorFactory"]
