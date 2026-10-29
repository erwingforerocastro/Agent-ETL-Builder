"""Unit tests for log and error redaction."""

from application.logging.redaction import REDACTED, redact_mapping, redact_value


def test_secret_keys_are_redacted_recursively() -> None:
    value = {
        "password": "hunter2",
        "nested": {"api_key": "key", "safe": "ok"},
        "items": [{"token": "abc"}],
        "empty": "",
    }

    assert redact_value(value) == {
        "password": REDACTED,
        "nested": {"api_key": REDACTED, "safe": "ok"},
        "items": [{"token": REDACTED}],
        "empty": "",
    }


def test_dsns_bearer_tokens_and_assignments_are_redacted() -> None:
    value = (
        "postgresql://user:secret@localhost/db Authorization: Bearer abc.def.ghi password=letmein"
    )

    redacted = redact_value(value)

    assert isinstance(redacted, str)
    assert "secret" not in redacted
    assert "abc.def.ghi" not in redacted
    assert "letmein" not in redacted
    assert "***:***@" in redacted
    assert "Authorization=[REDACTED]" in redacted
    assert "password=[REDACTED]" in redacted


def test_non_secret_values_are_preserved() -> None:
    value = {"path": "input.csv", "rows": 3, "ok": True, "missing": None}

    assert redact_value(value) == value


def test_redact_mapping_returns_a_plain_dictionary() -> None:
    result = redact_mapping({"secret": "x", "nested": {"password": "y"}})

    assert result == {"secret": REDACTED, "nested": {"password": REDACTED}}
