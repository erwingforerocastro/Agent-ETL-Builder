"""Plan validator implementation."""

import os
import re
from pathlib import Path

from application.ports.module_registry import ModuleRegistryPort
from application.ports.plan_validator import PlanValidatorPort
from domain.entities.plan import ExecutionPlan
from domain.errors import RegistryError


class PlanValidationError(RegistryError):
    """Plan validation failed."""


class PlanValidator(PlanValidatorPort):
    def __init__(
        self,
        registry: ModuleRegistryPort,
        *,
        workspace_root: Path | str | None = None,
        max_steps: int = 100,
        max_chunk_size: int = 10_000_000,
    ) -> None:
        self._registry = registry
        self._workspace_root = Path(workspace_root) if workspace_root else Path.cwd()
        self._max_steps = max_steps
        self._max_chunk_size = max_chunk_size

    def validate(self, plan: ExecutionPlan) -> None:
        self._validate_schema_basics(plan)
        self._validate_registry_entries(plan)
        self._validate_steps(plan)
        self._validate_paths(plan)
        self._validate_limits(plan)
        self._validate_security(plan)
        self._validate_approval(plan)

    def _validate_schema_basics(self, plan: ExecutionPlan) -> None:
        if plan.plan_version != "1.0":
            raise PlanValidationError(
                code="PLAN_INVALID_SCHEMA",
                message="plan_version must be 1.0",
                module=__name__,
                context={"plan_version": plan.plan_version},
            )
        if plan.on_error not in {"fail_fast", "continue"}:
            raise PlanValidationError(
                code="PLAN_INVALID_SCHEMA",
                message="on_error must be fail_fast or continue",
                module=__name__,
                context={"on_error": plan.on_error},
            )

    def _validate_registry_entries(self, plan: ExecutionPlan) -> None:
        operations = []
        if plan.source is not None:
            operations.append(plan.source.operation)
        if plan.destination is not None:
            operations.append(plan.destination.operation)
        for step in plan.transformations:
            operations.append(step.operation)
        for op in operations:
            metadata = self._registry.get(op)
            if metadata is None:
                raise PlanValidationError(
                    code="PLAN_UNKNOWN_OPERATION",
                    message="Operation is not allowlisted in the registry",
                    module=__name__,
                    context={"operation": op},
                )
            if plan.mode == "assessment" and plan.destination is None:
                # Assessment plans may call only read-only registry operations
                if "writes" in [s.lower() for s in metadata.side_effects]:
                    raise PlanValidationError(
                        code="PLAN_UNSAFE_OPERATION",
                        message="Assessment plans may only call read-only operations",
                        module=__name__,
                        context={"operation": op, "side_effects": metadata.side_effects},
                    )

    def _validate_steps(self, plan: ExecutionPlan) -> None:
        if len(plan.transformations) > self._max_steps:
            raise PlanValidationError(
                code="PLAN_TOO_MANY_STEPS",
                message="Plan exceeds maximum step count",
                module=__name__,
                context={
                    "steps": len(plan.transformations),
                    "max_steps": self._max_steps,
                },
            )
        # Check for duplicate step_ids already enforced in entity, but be defensive
        step_ids = [step.step_id for step in plan.transformations]
        if len(step_ids) != len(set(step_ids)):
            raise PlanValidationError(
                code="PLAN_DUPLICATE_STEP_ID",
                message="step_id values must be unique",
                module=__name__,
            )

    def _validate_paths(self, plan: ExecutionPlan) -> None:
        paths_to_check = []
        if plan.source and isinstance(plan.source.params, dict):
            for key in ("path", "paths", "file", "files"):
                if key in plan.source.params:
                    val = plan.source.params[key]
                    if isinstance(val, str):
                        paths_to_check.append(val)
                    elif isinstance(val, (list, tuple)):
                        for v in val:
                            if isinstance(v, str):
                                paths_to_check.append(v)
        if plan.destination and isinstance(plan.destination.params, dict):
            for key in ("path", "paths", "file", "files"):
                if key in plan.destination.params:
                    val = plan.destination.params[key]
                    if isinstance(val, str):
                        paths_to_check.append(val)
                    elif isinstance(val, (list, tuple)):
                        for v in val:
                            if isinstance(v, str):
                                paths_to_check.append(v)
        for p in paths_to_check:
            self._validate_single_path(p)

    def _validate_single_path(self, path_str: str) -> None:
        if not isinstance(path_str, str) or not path_str.strip():
            raise PlanValidationError(
                code="PLAN_INVALID_PATH",
                message="Path must be a non-empty string",
                module=__name__,
            )
        # Reject absolute paths
        if os.path.isabs(path_str) or path_str.startswith("/") or path_str.startswith("\\"):
            raise PlanValidationError(
                code="PLAN_PATH_NOT_ALLOWED",
                message="Absolute paths are not allowed",
                module=__name__,
                context={"path": path_str},
            )
        # Reject traversal
        if ".." in Path(path_str).parts:
            raise PlanValidationError(
                code="PLAN_PATH_TRAVERSAL",
                message="Path traversal is not allowed",
                module=__name__,
                context={"path": path_str},
            )
        # Resolve and ensure within workspace
        try:
            resolved = (self._workspace_root / path_str).resolve()
            workspace_resolved = self._workspace_root.resolve()
            if not str(resolved).startswith(str(workspace_resolved)):
                raise PlanValidationError(
                    code="PLAN_PATH_OUTSIDE_WORKSPACE",
                    message="Path must be within the workspace",
                    module=__name__,
                    context={"path": path_str},
                )
        except Exception as exc:
            if isinstance(exc, PlanValidationError):
                raise
            raise PlanValidationError(
                code="PLAN_INVALID_PATH",
                message="Invalid path",
                module=__name__,
                context={"path": path_str},
            ) from exc
        # Basic check for symlinks (best effort)
        try:
            full = self._workspace_root / path_str
            if full.exists() and full.is_symlink():
                raise PlanValidationError(
                    code="PLAN_PATH_SYMLINK",
                    message="Symlinks are not allowed",
                    module=__name__,
                    context={"path": path_str},
                )
        except PlanValidationError:
            raise
        except Exception:
            pass

    def _validate_limits(self, plan: ExecutionPlan) -> None:
        if plan.chunking.size <= 0 or plan.chunking.size > self._max_chunk_size:
            raise PlanValidationError(
                code="PLAN_INVALID_CHUNK_SIZE",
                message="Chunk size out of range",
                module=__name__,
                context={"size": plan.chunking.size, "max": self._max_chunk_size},
            )

    def _validate_security(self, plan: ExecutionPlan) -> None:
        dangerous_patterns = [
            r"\beval\s*\(",
            r"\bexec\s*\(",
            r"\b__import__\s*\(",
            r"\bimport\s+",
            r"subprocess",
            r"os\.system",
            r"shell\s*=",
        ]
        # Check all string values in params
        def check_obj(obj, path=""):
            if isinstance(obj, str):
                for pat in dangerous_patterns:
                    if re.search(pat, obj, re.IGNORECASE):
                        raise PlanValidationError(
                            code="PLAN_UNSAFE_CONTENT",
                            message="Unsafe content detected",
                            module=__name__,
                            context={"path": path},
                        )
            elif isinstance(obj, dict):
                for k, v in obj.items():
                    check_obj(v, f"{path}.{k}" if path else k)
            elif isinstance(obj, (list, tuple)):
                for i, v in enumerate(obj):
                    check_obj(v, f"{path}[{i}]" if path else f"[{i}]")

        all_objs = []
        if plan.source:
            all_objs.append(plan.source.params)
        if plan.destination:
            all_objs.append(plan.destination.params)
        for step in plan.transformations:
            all_objs.append(step.params)
        for obj in all_objs:
            check_obj(obj)

    def _validate_approval(self, plan: ExecutionPlan) -> None:
        if not plan.approval_required:
            return
        # Writes, DDL, destructive transformations require approval
        write_indicators = ["write", "save", "insert", "update", "delete", "drop", "truncate", "load"]
        destructive_ops = ["drop_duplicate_rows"]  # example, but generally check side effects
        needs_approval = False
        if plan.destination is not None:
            op = plan.destination.operation.lower()
            if any(w in op for w in write_indicators):
                needs_approval = True
        for step in plan.transformations:
            op = step.operation.lower()
            if any(w in op for w in write_indicators) or op in destructive_ops:
                # Check if it's destructive - be conservative
                needs_approval = True
        # Also check side effects from registry
        if plan.destination:
            meta = self._registry.get(plan.destination.operation)
            if meta and "writes" in [s.lower() for s in meta.side_effects]:
                needs_approval = True
        for step in plan.transformations:
            meta = self._registry.get(step.operation)
            if meta and any(s.lower() in ["writes", "ddl", "destructive"] for s in meta.side_effects):
                needs_approval = True
        if needs_approval and not plan.approval_required:
            raise PlanValidationError(
                code="PLAN_APPROVAL_REQUIRED",
                message="This plan requires approval",
                module=__name__,
            )
        # If approval_required is True, that's fine - will be enforced by workflow
