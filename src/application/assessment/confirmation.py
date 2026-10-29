"""Build an executable pipeline plan from a confirmed assessment."""

from __future__ import annotations

import os
from pathlib import PurePosixPath

from domain.entities.assessment import AssessmentReport
from domain.entities.plan import (
    ExecutionPlan,
    PlanChunking,
    PlanDestination,
    PlanSource,
)


def build_pipeline_plan(
    assessment: AssessmentReport,
    *,
    destination: str,
) -> ExecutionPlan:
    """Build the deterministic pipeline plan confirmed by the user."""
    if not destination.strip():
        raise ValueError("destination must not be blank")
    draft = assessment.draft_plan
    source_path = str(draft.source_params.get("path", ""))
    if source_path and _same_workspace_path(source_path, destination):
        raise ValueError("destination must not overwrite the source")
    return ExecutionPlan(
        plan_version="1.0",
        mode="pipeline",
        run_id=assessment.run_id,
        name=f"{draft.name}_load",
        description=f"Write the confirmed assessment result for {assessment.source_id}",
        source=PlanSource(
            operation=draft.source_operation,
            params=dict(draft.source_params),
        ),
        transformations=draft.transformations,
        destination=PlanDestination(
            operation="save_csv",
            params={"path": destination},
        ),
        chunking=PlanChunking(
            enabled=draft.chunking.enabled,
            size=draft.chunking.size,
        ),
        on_error="fail_fast",
        approval_required=True,
    )


def _same_workspace_path(left: str, right: str) -> bool:
    def normalize(value: str) -> tuple[str, ...]:
        parts = PurePosixPath(value.strip().replace("\\", "/")).parts
        return tuple(part.casefold() for part in parts) if os.name == "nt" else tuple(parts)

    return normalize(left) == normalize(right)


__all__ = ["build_pipeline_plan"]
