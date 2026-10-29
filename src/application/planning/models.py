"""Application models shared by natural-language planning."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourceSchema:
    """Column names and dtypes visible to the plan builder."""

    columns: tuple[str, ...] = ()
    dtypes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        columns = tuple(self.columns)
        dtypes = tuple(self.dtypes)
        object.__setattr__(self, "columns", columns)
        object.__setattr__(self, "dtypes", dtypes)
        if any(not column.strip() for column in columns):
            raise ValueError("columns must not be blank")
        if len(set(columns)) != len(columns):
            raise ValueError("columns must be unique")
        if dtypes and len(dtypes) != len(columns):
            raise ValueError("dtypes must match the column count")


__all__ = ["SourceSchema"]
