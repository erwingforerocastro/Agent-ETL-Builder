"""Unit tests for the bounded source schema probe."""

from pathlib import Path

import pytest

from application.planning.models import SourceSchema
from domain.errors import IngestionError
from infrastructure.assessment.source_reader import WorkspaceSourceReader
from infrastructure.planning.source_schema import WorkspaceSourceSchemaProbe
from infrastructure.validation.path_probe import FilesystemWorkspaceProbe


def _probe(tmp_path: Path) -> WorkspaceSourceSchemaProbe:
    reader = WorkspaceSourceReader(FilesystemWorkspaceProbe(tmp_path))
    return WorkspaceSourceSchemaProbe(reader, sample_rows=1)


def test_probe_returns_columns_and_dtypes(tmp_path: Path) -> None:
    (tmp_path / "input.csv").write_text("name,score\nAda,1\nBob,2\n", encoding="utf-8")

    schema = _probe(tmp_path).inspect("input.csv")

    assert schema.columns == ("name", "score")
    assert len(schema.dtypes) == 2


def test_probe_returns_an_empty_schema_for_an_empty_csv(tmp_path: Path) -> None:
    (tmp_path / "empty.csv").write_text("", encoding="utf-8")

    assert _probe(tmp_path).inspect("empty.csv") == SourceSchema()


def test_probe_reports_a_missing_source(tmp_path: Path) -> None:
    with pytest.raises(IngestionError) as caught:
        _probe(tmp_path).inspect("missing.csv")

    assert caught.value.code == "SOURCE_NOT_FOUND"


def test_probe_rejects_unsafe_paths(tmp_path: Path) -> None:
    with pytest.raises(IngestionError) as caught:
        _probe(tmp_path).inspect("../input.csv")

    assert caught.value.code == "SOURCE_REFERENCE_INVALID"


def test_source_schema_validates_columns_and_dtypes() -> None:
    with pytest.raises(ValueError, match="blank"):
        SourceSchema(columns=(" ",))
    with pytest.raises(ValueError, match="unique"):
        SourceSchema(columns=("a", "a"))
    with pytest.raises(ValueError, match="dtypes"):
        SourceSchema(columns=("a",), dtypes=("string", "integer"))
