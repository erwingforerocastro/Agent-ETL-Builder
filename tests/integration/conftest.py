"""Shared integration-test fixtures."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.integration.postgres_test_cluster import (
    PostgresCluster,
    running_postgres_cluster,
)


@pytest.fixture(scope="session")
def postgres_cluster(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PostgresCluster]:
    data_dir = tmp_path_factory.mktemp("postgres-data")
    with running_postgres_cluster(data_dir) as cluster:
        yield cluster
