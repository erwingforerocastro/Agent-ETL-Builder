"""Unit tests for stable source identifiers and hashing."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

from domain.errors import IngestionError, SandboxError
from infrastructure.ingestion.identifiers import (
    artifact_id,
    canonical_file_uri,
    credential_free_uri,
    file_content_hash,
    frame_content_hash,
    frame_schema_hash,
    sanitize_identifier,
    source_id_for,
    source_identity_for_file,
    source_identity_for_frame,
)


def test_source_id_is_stable_and_type_sensitive() -> None:
    first = source_id_for("csv", "C:/data/input.csv")
    second = source_id_for("csv", "C:/data/input.csv")
    other_type = source_id_for("parquet", "C:/data/input.csv")

    assert first == second
    assert first != other_type
    assert first.startswith("src_")
    assert len(first) <= 128


def test_source_id_ignores_uri_credentials() -> None:
    with_credentials = source_id_for(
        "postgresql",
        "postgresql://user:secret@localhost:5432/warehouse",
    )
    without_credentials = source_id_for(
        "postgresql",
        "postgresql://localhost:5432/warehouse",
    )

    assert with_credentials == without_credentials
    assert "secret" not in with_credentials


def test_credential_free_uri_removes_user_information() -> None:
    assert (
        credential_free_uri("postgresql://user:secret@host:5432/db") == "postgresql://host:5432/db"
    )
    assert credential_free_uri("C:/data/input.csv") == "C:/data/input.csv"


def test_credential_free_uri_removes_sensitive_query_values() -> None:
    assert (
        credential_free_uri(
            "postgresql://user:secret@host/db?password=secret&sslmode=require&user=admin"
        )
        == "postgresql://host/db?sslmode=require"
    )


def test_source_id_rejects_unknown_type_and_blank_uri() -> None:
    with pytest.raises(ValueError, match="unsupported source_type"):
        source_id_for("xml", "input.xml")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="canonical_uri"):
        source_id_for("csv", " ")


def test_canonical_file_uri_is_absolute_and_stable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "input.csv"
    path.write_text("name\nAda\n", encoding="utf-8")

    first = canonical_file_uri(path)
    second = canonical_file_uri(path)
    monkeypatch.chdir(tmp_path)

    assert first == second == canonical_file_uri("input.csv")
    assert ".." not in first
    if os.name == "nt":
        assert first == first.lower()


def test_sanitize_identifier_removes_path_characters() -> None:
    assert sanitize_identifier("../run/../id") == "run_id"
    assert sanitize_identifier(" ") == "x"
    assert len(sanitize_identifier("a" * 200, max_length=20)) == 20
    with pytest.raises(ValueError, match="max_length"):
        sanitize_identifier("value", max_length=0)


def test_artifact_id_is_safe_and_deterministic() -> None:
    first = artifact_id("../run", "src_abc", "profile/chunk", 3)
    second = artifact_id("../run", "src_abc", "profile/chunk", 3)

    assert first == second
    assert "/" not in first
    assert ".." not in first
    assert first.endswith("_000003")
    assert len(first) <= 180


def test_artifact_id_without_chunk_index() -> None:
    assert artifact_id("../run", "src_abc", "profile/chunk") == "run_src_abc_profile_chunk"


def test_canonical_file_uri_wraps_resolution_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_resolve(self: Path, strict: bool = False) -> Path:
        del self, strict
        raise OSError("boom")

    monkeypatch.setattr(Path, "resolve", fail_resolve)

    with pytest.raises(IngestionError, match="could not be resolved"):
        canonical_file_uri("input.csv")


def test_file_content_hash_preserves_sandbox_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_open(self: Path, mode: str = "r", *args: object, **kwargs: object) -> None:
        del self, mode, args, kwargs
        raise SandboxError(
            code="SANDBOX_PATH_DENIED",
            message="denied",
            module="test",
        )

    monkeypatch.setattr(Path, "open", fail_open)

    with pytest.raises(SandboxError, match="denied"):
        file_content_hash("input.csv")


def test_artifact_id_rejects_invalid_chunk_index() -> None:
    with pytest.raises(ValueError, match="chunk_index"):
        artifact_id("run", "src", "chunk", -1)
    with pytest.raises(ValueError, match="chunk_index"):
        artifact_id("run", "src", "chunk", True)


def test_file_content_hash_changes_with_content(tmp_path: Path) -> None:
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"
    first.write_text("name\nAda\n", encoding="utf-8")
    second.write_text("name\nGrace\n", encoding="utf-8")

    first_hash = file_content_hash(first)
    second_hash = file_content_hash(second)

    assert first_hash.startswith("sha256:")
    assert first_hash == file_content_hash(first)
    assert first_hash != second_hash


def test_file_content_hash_wraps_missing_files(tmp_path: Path) -> None:
    with pytest.raises(IngestionError, match="could not be read"):
        file_content_hash(tmp_path / "missing.csv")


def test_frame_hashes_detect_schema_and_value_changes() -> None:
    frame = pd.DataFrame({"id": [1, 2], "name": ["Ada", "Bob"]})
    same = frame.copy()
    changed_value = frame.copy()
    changed_value.loc[0, "name"] = "Grace"
    changed_schema = frame.rename(columns={"name": "full_name"})

    assert frame_schema_hash(frame) == frame_schema_hash(same)
    assert frame_schema_hash(frame) != frame_schema_hash(changed_schema)
    assert frame_content_hash(frame) == frame_content_hash(same)
    assert frame_content_hash(frame) != frame_content_hash(changed_value)
    assert frame_content_hash(frame).startswith("sha256:")


def test_frame_content_hash_handles_unhashable_values() -> None:
    frame = pd.DataFrame({"payload": [[1, 2], [3]]})
    same = pd.DataFrame({"payload": [[1, 2], [3]]})
    changed = pd.DataFrame({"payload": [[1, 2], [4]]})

    assert frame_content_hash(frame) == frame_content_hash(same)
    assert frame_content_hash(frame) != frame_content_hash(changed)


def test_frame_content_hash_handles_mixed_values() -> None:
    values: list[object] = [
        None,
        {"key": [1, 2]},
        float("nan"),
        float("inf"),
        True,
        pd.Timestamp("2026-01-01"),
    ]
    changed_values: list[object] = [
        None,
        {"key": [1, 3]},
        float("nan"),
        float("inf"),
        True,
        pd.Timestamp("2026-01-01"),
    ]
    frame = pd.DataFrame({"payload": values})
    same = pd.DataFrame({"payload": values})
    changed = pd.DataFrame({"payload": changed_values})

    assert frame_content_hash(frame) == frame_content_hash(same)
    assert frame_content_hash(frame) != frame_content_hash(changed)


def test_source_identity_for_frame_is_stable() -> None:
    frame = pd.DataFrame({"id": [1]})
    first = source_identity_for_frame(
        frame,
        source_type="csv",
        canonical_uri="C:/data/input.csv",
    )
    second = source_identity_for_frame(
        frame,
        source_type="csv",
        canonical_uri="C:/data/input.csv",
    )

    assert first == second
    assert first.row_count == 1
    assert first.content_hash.startswith("sha256:")
    assert first.schema_hash.startswith("sha256:")
    assert first.to_dict()["source_id"] == first.source_id


def test_source_identity_for_file_uses_file_bytes(tmp_path: Path) -> None:
    path = tmp_path / "input.csv"
    path.write_text("name\nAda\n", encoding="utf-8")
    frame = pd.read_csv(path)

    identity = source_identity_for_file(path, frame, source_type="csv")

    assert identity.row_count == 1
    assert identity.source_id == source_id_for("csv", canonical_file_uri(path))
    assert identity.content_hash == file_content_hash(path)


def test_source_identity_accepts_a_precomputed_content_hash() -> None:
    frame = pd.DataFrame({"id": [1]})

    identity = source_identity_for_frame(
        frame,
        source_type="postgresql",
        canonical_uri="postgresql://localhost/db#public.people",
        content_hash="sha256:fixed",
    )

    assert identity.content_hash == "sha256:fixed"
