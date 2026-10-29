"""Integration tests for profiling an ingested CSV source."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from application.profiling.models import ProfileRequest
from application.use_cases.profile_source import ProfileSourceUseCase
from infrastructure.ingestion.csv import iter_csv_chunks
from infrastructure.ingestion.identifiers import (
    canonical_file_uri,
    file_content_hash,
    source_id_for,
)
from infrastructure.profiling.artifacts import FilesystemProfileWriter
from infrastructure.profiling.pandas_profiler import PandasChunkProfiler


def test_csv_source_is_profiled_with_stable_identity_and_artifacts(tmp_path: Path) -> None:
    path = tmp_path / "orders.csv"
    path.write_text(
        "order_id,amount,note\n1,10.5,ok\n2,20.0,\n2,20.0,\n",
        encoding="utf-8",
    )
    original = path.read_bytes()
    source_id = source_id_for("csv", canonical_file_uri(path))
    request = ProfileRequest(
        run_id="run-1",
        source_id=source_id,
        source_type="csv",
        chunk_size=1,
        content_hash=file_content_hash(path),
    )
    artifacts_root = tmp_path / "artifacts"
    writer = FilesystemProfileWriter(artifacts_root)
    use_case = ProfileSourceUseCase(PandasChunkProfiler(), writer)

    outcome = use_case.execute(
        iter_csv_chunks(path=str(path), chunk_size=1),
        request,
    )

    assert path.read_bytes() == original
    assert outcome.report.row_count == 3
    assert outcome.report.chunk_count == 3
    assert outcome.report.content_hash == file_content_hash(path)
    assert outcome.report.schema_hash is not None
    assert outcome.report.schema_hash.startswith("sha256:")
    assert Path(outcome.artifacts.quality_path).exists()
    assert Path(outcome.artifacts.info_path).exists()
    assert len(outcome.artifacts.chunk_paths) == 3
    assert all(Path(item).exists() for item in outcome.artifacts.chunk_paths)

    duplicates = next(
        metric for metric in outcome.report.metrics if metric.metric == "duplicate_rows"
    )
    assert duplicates.numerator == 2
    assert duplicates.denominator == 3

    with Path(outcome.artifacts.quality_path).open(
        "r",
        encoding="utf-8",
        newline="",
    ) as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["source_id"] == source_id
    assert any(row["metric"] == "accuracy" and row["value"] == "N/A" for row in rows)

    payload = json.loads(Path(outcome.artifacts.info_path).read_text(encoding="utf-8"))
    assert payload["source"]["row_count"] == 3
    assert payload["profile"]["chunk_count"] == 3
    assert [column["name"] for column in payload["columns"]] == [
        "order_id",
        "amount",
        "note",
    ]
