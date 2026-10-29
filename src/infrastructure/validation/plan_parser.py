"""Pydantic-backed plan parser adapter."""

from __future__ import annotations

from collections.abc import Mapping

from application.ports.plan_parser import PlanParserPort
from domain.entities.plan import ExecutionPlan
from infrastructure.validation.plan_schema import parse_plan


class PydanticPlanParser(PlanParserPort):
    """Parses JSON-compatible plan payloads with the strict plan schema."""

    def parse(self, payload: Mapping[str, object]) -> ExecutionPlan:
        return parse_plan(payload)


__all__ = ["PydanticPlanParser"]
