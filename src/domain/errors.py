"""Shared ETL error contracts."""

from collections.abc import Mapping


class EtlError(Exception):
    """Base error with stable, redaction-ready metadata."""

    code: str
    message: str
    module: str
    retryable: bool
    context: dict[str, object]

    def __init__(
        self,
        *,
        code: str,
        message: str,
        module: str,
        retryable: bool = False,
        context: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.module = module
        self.retryable = retryable
        self.context = dict(context or {})

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "type": type(self).__name__,
            "module": self.module,
            "message": self.message,
            "retryable": self.retryable,
            "context": dict(self.context),
        }


class TransformationError(EtlError):
    """A deterministic data transformation failed."""


class IngestionError(EtlError):
    """A source could not be read."""


class LoadError(EtlError):
    """A destination could not be written."""


class ProfilingError(EtlError):
    """A source could not be profiled or its profile could not be merged."""


class RegistryError(EtlError):
    """The module registry is invalid or a lookup failed."""


class PlanValidationError(EtlError):
    """A plan failed schema, registry, argument, path, limit, security, or approval checks."""


class SandboxError(EtlError):
    """Sandbox policy or a resource limit stopped execution."""


class WorkflowError(EtlError):
    """A run could not complete its lifecycle."""


class RunNotFoundError(WorkflowError):
    """No checkpoint exists for the requested run."""

    def __init__(self, *, run_id: str) -> None:
        super().__init__(
            code="RUN_NOT_FOUND",
            message="Run was not found",
            module=__name__,
            context={"run_id": run_id},
        )


class RunAlreadyExistsError(WorkflowError):
    """A checkpoint with the requested run id already exists."""

    def __init__(self, *, run_id: str) -> None:
        super().__init__(
            code="RUN_ALREADY_EXISTS",
            message="Run already exists",
            module=__name__,
            context={"run_id": run_id},
        )


class RunInvalidStateError(WorkflowError):
    """An operation is not valid for the run's current state."""

    def __init__(self, *, status: str, operation: str) -> None:
        super().__init__(
            code="RUN_INVALID_STATE",
            message="Run is not in a state that supports this operation",
            module=__name__,
            context={"status": status, "operation": operation},
        )


class RunCancelledError(WorkflowError):
    """The run was cancelled before it could succeed."""

    def __init__(self) -> None:
        super().__init__(
            code="RUN_CANCELLED",
            message="Run was cancelled",
            module=__name__,
        )


class RunClarificationExhaustedError(WorkflowError):
    """The clarification and repair budget was exhausted."""

    def __init__(self, *, attempts: int) -> None:
        super().__init__(
            code="RUN_CLARIFICATION_EXHAUSTED",
            message="The clarification and repair attempt limit was reached",
            module=__name__,
            context={"attempts": attempts},
        )


class RunApprovalRejectedError(WorkflowError):
    """A human rejected the plan."""

    def __init__(self) -> None:
        super().__init__(
            code="RUN_APPROVAL_REJECTED",
            message="Plan approval was rejected",
            module=__name__,
        )


class RunApprovalTimeoutError(WorkflowError):
    """No approval decision arrived before the deadline."""

    def __init__(self, *, timeout_seconds: float) -> None:
        super().__init__(
            code="RUN_APPROVAL_TIMEOUT",
            message="Plan approval timed out",
            module=__name__,
            context={"timeout_seconds": timeout_seconds},
        )


class RunPlanStaleError(WorkflowError):
    """The plan or registry changed after validation."""

    def __init__(self, *, reason: str) -> None:
        super().__init__(
            code="RUN_PLAN_STALE",
            message="Plan is stale and must be validated again",
            module=__name__,
            context={"reason": reason},
        )


class RunExecutionError(WorkflowError):
    """Execution failed with an unexpected error."""

    def __init__(self, *, error_type: str) -> None:
        super().__init__(
            code="RUN_EXECUTION_FAILED",
            message="Run execution failed",
            module=__name__,
            context={"error_type": error_type},
        )


class RunIntakeError(WorkflowError):
    """Plan intake failed with an unexpected error."""

    def __init__(self, *, error_type: str) -> None:
        super().__init__(
            code="RUN_INTAKE_FAILED",
            message="Plan intake failed",
            module=__name__,
            context={"error_type": error_type},
        )


class RunApprovalError(WorkflowError):
    """The approval gateway failed unexpectedly."""

    def __init__(self, *, error_type: str) -> None:
        super().__init__(
            code="RUN_APPROVAL_FAILED",
            message="Approval gateway failed",
            module=__name__,
            context={"error_type": error_type},
        )


__all__ = [
    "EtlError",
    "IngestionError",
    "LoadError",
    "PlanValidationError",
    "ProfilingError",
    "RegistryError",
    "RunAlreadyExistsError",
    "RunApprovalError",
    "RunApprovalRejectedError",
    "RunApprovalTimeoutError",
    "RunCancelledError",
    "RunClarificationExhaustedError",
    "RunExecutionError",
    "RunIntakeError",
    "RunInvalidStateError",
    "RunNotFoundError",
    "RunPlanStaleError",
    "SandboxError",
    "TransformationError",
    "WorkflowError",
]
