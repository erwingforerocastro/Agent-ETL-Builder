"""Unit tests for profiling artifact persistence."""

from __future__ import annotations

import csv
import json
import os
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from application.profiling.models import ProfileRequest
from domain.entities.profiling import ProfileReport
from domain.errors import ProfilingError
from infrastructure.profiling.artifacts import FilesystemProfileWriter
from infrastructure.profiling.pandas_profiler import PandasChunkProfiler


def _request() -> ProfileRequest:
    return ProfileRequest(
        run_id="run-1",
        source_id="src_abc",
        source_type="csv",
    )


def _report() -> ProfileReport:
    request = _request()
    profiler = PandasChunkProfiler()
    record = profiler.profile_chunk(
        pd.DataFrame({"id": [1, 2], "name": ["Ada", ""]}),
        chunk_index=0,
        request=request,
    )
    return profiler.merge([record], request=request)


def _write_report(tmp_path: Path) -> tuple[ProfileReport, FilesystemProfileWriter]:
    request = _request()
    profiler = PandasChunkProfiler()
    writer = FilesystemProfileWriter(tmp_path / "artifacts")
    record = profiler.profile_chunk(
        pd.DataFrame({"id": [1, 2], "name": ["Ada", ""]}),
        chunk_index=0,
        request=request,
    )
    writer.write_chunk(request, record)
    report = profiler.merge([record], request=request)
    return report, writer


def test_writes_chunk_quality_and_info_artifacts(tmp_path: Path) -> None:
    report, writer = _write_report(tmp_path)

    artifacts = writer.write_report(report)

    quality = Path(artifacts.quality_path)
    info = Path(artifacts.info_path)
    assert quality.name == "src_abc_csv_quality.csv"
    assert info.name == "src_abc_csv_info.json"
    assert quality.parent.name == "run-1"
    assert len(artifacts.chunk_paths) == 1
    assert Path(artifacts.chunk_paths[0]).exists()

    with quality.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["chunk_merge_method"]
    assert rows[0]["metric_definition_version"] == "1.0.0"
    accuracy = next(row for row in rows if row["metric"] == "accuracy")
    assert accuracy["value"] == "N/A"
    assert accuracy["formula"] == "N/A (formula not provided)"
    assert accuracy["status"] == "not_applicable"
    assert "null_count" in rows[0]["details"]

    payload = json.loads(info.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.0.0"
    assert payload["source"]["source_id"] == "src_abc"
    assert payload["profile"]["scope"] == "full"
    assert payload["quality"]["metrics"]
    assert [column["name"] for column in payload["columns"]] == ["id", "name"]

    chunk_payload = json.loads(Path(artifacts.chunk_paths[0]).read_text(encoding="utf-8"))
    assert chunk_payload["run_id"] == "run-1"
    assert chunk_payload["profile"]["chunk_index"] == 0
    assert chunk_payload["profile"]["row_count"] == 2


def test_unsafe_identifiers_are_rejected_before_writing(tmp_path: Path) -> None:
    writer = FilesystemProfileWriter(tmp_path / "artifacts")
    report = _report()

    with pytest.raises(ProfilingError) as run_error:
        writer.write_report(replace(report, run_id="../run"))
    with pytest.raises(ProfilingError) as source_error:
        writer.write_report(replace(report, source_id="../source"))
    with pytest.raises(ProfilingError) as reserved_error:
        writer.write_report(replace(report, run_id="CON"))
    with pytest.raises(ProfilingError) as trailing_dot_error:
        writer.write_report(replace(report, run_id="run."))

    assert run_error.value.code == "PROFILE_ARTIFACT_PATH_INVALID"
    assert source_error.value.code == "PROFILE_ARTIFACT_PATH_INVALID"
    assert reserved_error.value.code == "PROFILE_ARTIFACT_PATH_INVALID"
    assert trailing_dot_error.value.code == "PROFILE_ARTIFACT_PATH_INVALID"
    assert not (tmp_path / "artifacts").exists()


def test_quality_csv_neutralizes_formula_cells(tmp_path: Path) -> None:
    writer = FilesystemProfileWriter(tmp_path / "artifacts")
    report = _report()
    metric = replace(report.metrics[0], subject="=cmd")
    report = replace(report, metrics=(metric,))

    artifacts = writer.write_report(report)

    with Path(artifacts.quality_path).open("r", encoding="utf-8", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["subject"] == "'=cmd"


def test_chunk_identifier_is_rejected(tmp_path: Path) -> None:
    writer = FilesystemProfileWriter(tmp_path / "artifacts")
    request = _request()
    profiler = PandasChunkProfiler()
    record = profiler.profile_chunk(
        pd.DataFrame({"id": [1]}),
        chunk_index=0,
        request=request,
    )

    with pytest.raises(ProfilingError) as caught:
        writer.write_chunk(replace(request, run_id="run/child"), record)

    assert caught.value.code == "PROFILE_ARTIFACT_PATH_INVALID"


def test_write_failure_is_structured_and_cleans_temporary_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _report()
    writer = FilesystemProfileWriter(tmp_path / "artifacts")

    def fail_replace(source: object, destination: object) -> None:
        del source, destination
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(ProfilingError) as caught:
        writer.write_report(report)

    assert caught.value.code == "PROFILE_ARTIFACT_WRITE_FAILED"
    assert caught.value.context["error_type"] == "OSError"
    assert not list((tmp_path / "artifacts").rglob("*.tmp"))
