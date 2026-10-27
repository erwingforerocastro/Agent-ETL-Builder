from domain.errors import TransformationError


def test_transformation_error_serializes_stable_metadata() -> None:
    error = TransformationError(
        code="TRANSFORMATION_TEST",
        message="safe message",
        module="transformations.test",
        retryable=True,
        context={"column": "amount"},
    )

    assert str(error) == "safe message"
    assert error.to_dict() == {
        "code": "TRANSFORMATION_TEST",
        "type": "TransformationError",
        "module": "transformations.test",
        "message": "safe message",
        "retryable": True,
        "context": {"column": "amount"},
    }
