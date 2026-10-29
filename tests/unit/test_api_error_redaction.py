"""API error envelopes must not leak secret-like context values."""

from application.logging.redaction import REDACTED
from domain.errors import TransformationError
from interfaces.api.schemas.runs import ErrorResponse


def test_error_context_is_redacted() -> None:
    error = TransformationError(
        code="TRANSFORMATION_FAILED",
        message="failed",
        module="test",
        context={
            "password": "secret",
            "nested": {"token": "abc", "path": "output.csv"},
        },
    )

    response = ErrorResponse.from_error(error)

    assert response.details == {
        "password": REDACTED,
        "nested": {"token": REDACTED, "path": "output.csv"},
    }
