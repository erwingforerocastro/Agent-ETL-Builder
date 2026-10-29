"""Source schema inspection contract for plan synthesis."""

from typing import Protocol

from application.planning.models import SourceSchema


class SourceSchemaPort(Protocol):
    """Returns a bounded schema view of a workspace source."""

    def inspect(self, source: str) -> SourceSchema: ...


__all__ = ["SourceSchemaPort"]
