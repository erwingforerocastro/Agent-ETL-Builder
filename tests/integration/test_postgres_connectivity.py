"""Integration tests for PostgreSQL connectivity on a temporary cluster."""

from __future__ import annotations

import os
import secrets
import shutil
import socket
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import psycopg
import pytest

from domain.errors import IngestionError, LoadError
from infrastructure.database.config import PostgresConfig, SslMode
from infrastructure.database.postgres import PostgresDatabase


@dataclass(frozen=True, slots=True)
class _Cluster:
    dsn: str
    cert_path: Path | None


def _exe(name: str) -> str:
    return f"{name}.exe" if os.name == "nt" else name


def _has_server_binaries(candidate: Path) -> bool:
    return all((candidate / _exe(name)).exists() for name in ("initdb", "postgres", "pg_ctl"))


def _find_pg_bin() -> Path | None:
    configured = os.getenv("AGENT_ETL_TEST_PG_BIN")
    if configured:
        candidate = Path(configured)
        if _has_server_binaries(candidate):
            return candidate
    found = shutil.which("initdb")
    if found is not None:
        candidate = Path(found).parent
        if _has_server_binaries(candidate):
            return candidate
    candidates = [
        *sorted(Path("/usr/lib/postgresql").glob("*/bin"), reverse=True),
        *sorted(Path(r"C:\Program Files\PostgreSQL").glob("*/bin"), reverse=True),
    ]
    for candidate in candidates:
        if _has_server_binaries(candidate):
            return candidate
    return None


def _run(
    command: list[str],
    *,
    timeout: int = 120,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=check,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _tail(path: Path) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "server log unavailable"
    return "\n".join(lines[-10:])


def _find_openssl() -> str | None:
    configured = os.getenv("AGENT_ETL_TEST_OPENSSL")
    if configured and Path(configured).exists():
        return configured
    found = shutil.which("openssl")
    if found is not None:
        return found
    candidates = (
        Path(r"C:\Program Files\Git\usr\bin\openssl.exe"),
        Path(r"C:\Program Files\Git\mingw64\bin\openssl.exe"),
    )
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def _generate_certificate(data_dir: Path) -> Path | None:
    openssl = _find_openssl()
    if openssl is None:
        return None
    cert = data_dir / "server.crt"
    key = data_dir / "server.key"
    try:
        _run(
            [
                openssl,
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "2",
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=DNS:localhost,IP:127.0.0.1",
                "-keyout",
                str(key),
                "-out",
                str(cert),
            ],
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    key.chmod(0o600)
    return cert


def _wait_until_ready(
    dsn: str,
    process: subprocess.Popen[bytes],
    log_path: Path,
) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"PostgreSQL exited with {process.returncode}:\n{_tail(log_path)}")
        try:
            with psycopg.connect(dsn, connect_timeout=1, sslmode="disable"):
                return
        except psycopg.OperationalError:
            time.sleep(0.2)
    raise RuntimeError(f"PostgreSQL did not become ready:\n{_tail(log_path)}")


@pytest.fixture(scope="session")
def postgres_cluster(tmp_path_factory: pytest.TempPathFactory) -> Iterator[_Cluster]:
    bin_dir = _find_pg_bin()
    if bin_dir is None:
        pytest.skip("PostgreSQL server binaries are not available")

    data_dir = tmp_path_factory.mktemp("postgres-data")
    try:
        _run(
            [
                str(bin_dir / _exe("initdb")),
                "-D",
                str(data_dir),
                "-U",
                "postgres",
                "-A",
                "trust",
                "--no-locale",
                "--encoding=UTF8",
            ]
        )
    except (OSError, subprocess.SubprocessError) as exc:
        pytest.skip(f"could not initialize PostgreSQL: {exc}")

    port = _free_port()
    log_path = data_dir / "server.log"
    log = log_path.open("wb")
    cert_path = _generate_certificate(data_dir)
    command = [
        str(bin_dir / _exe("postgres")),
        "-D",
        str(data_dir),
        "-p",
        str(port),
        "-h",
        "127.0.0.1",
    ]
    if cert_path is not None:
        command.extend(
            [
                "-c",
                "ssl=on",
                "-c",
                f"ssl_cert_file={cert_path}",
                "-c",
                f"ssl_key_file={data_dir / 'server.key'}",
            ]
        )
    creation_flags = 0
    if os.name == "nt":
        windows = cast(Any, subprocess)
        creation_flags = windows.DETACHED_PROCESS | windows.CREATE_NEW_PROCESS_GROUP
    process = subprocess.Popen(
        command,
        stdout=log,
        stderr=subprocess.STDOUT,
        creationflags=creation_flags,
    )
    dsn = f"postgresql://postgres@127.0.0.1:{port}/postgres"
    try:
        _wait_until_ready(dsn, process, log_path)
        yield _Cluster(dsn=dsn, cert_path=cert_path)
    finally:
        log.close()
        _run(
            [
                str(bin_dir / _exe("pg_ctl")),
                "-D",
                str(data_dir),
                "-m",
                "immediate",
                "stop",
            ],
            check=False,
            timeout=30,
        )
        if process.poll() is None:
            process.terminate()


def _database(cluster: _Cluster, *, sslmode: SslMode = "disable") -> PostgresDatabase:
    return PostgresDatabase(
        PostgresConfig(
            dsn=cluster.dsn,
            sslmode=sslmode,
            connect_timeout_seconds=5,
            statement_timeout_ms=5_000,
        )
    )


def _schema_name() -> str:
    return f"agent_etl_test_{secrets.token_hex(4)}"


def _prepare(database: PostgresDatabase, schema: str) -> None:
    with database.connect() as session:
        session.execute(f'CREATE SCHEMA "{schema}"')
        session.execute(
            f'CREATE TABLE "{schema}".people (id integer PRIMARY KEY, name text NOT NULL)'
        )


def _drop(database: PostgresDatabase, schema: str) -> None:
    with database.connect() as session:
        session.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def _insert_duplicate(database: PostgresDatabase, schema: str) -> None:
    with database.connect() as session:
        session.execute(
            f'INSERT INTO "{schema}".people (id, name) VALUES (%s, %s)',
            (1, "Ada"),
        )
        session.execute(
            f'INSERT INTO "{schema}".people (id, name) VALUES (%s, %s)',
            (1, "Bob"),
        )


def test_parameterized_read_write_in_temporary_schema(postgres_cluster: _Cluster) -> None:
    database = _database(postgres_cluster)
    schema = _schema_name()
    payload = "O'Brien; DROP TABLE people; --"
    _prepare(database, schema)
    try:
        with database.connect() as session:
            assert (
                session.execute(
                    f'INSERT INTO "{schema}".people (id, name) VALUES (%s, %s)',
                    (1, payload),
                )
                == 1
            )
            result = session.fetch_all(
                f'SELECT id, name FROM "{schema}".people WHERE name = %s',
                (payload,),
            )
        assert result.columns == ("id", "name")
        assert result.rows == ((1, payload),)
    finally:
        _drop(database, schema)


def test_read_only_session_rejects_writes(postgres_cluster: _Cluster) -> None:
    database = _database(postgres_cluster)
    schema = _schema_name()
    _prepare(database, schema)
    try:
        with (
            pytest.raises(IngestionError) as captured,
            database.connect(read_only=True) as session,
        ):
            session.execute(
                f'INSERT INTO "{schema}".people (id, name) VALUES (%s, %s)',
                (1, "Ada"),
            )
        assert captured.value.code == "DATABASE_READ_FAILED"

        with database.connect(read_only=True) as session:
            result = session.fetch_all(f'SELECT count(*) FROM "{schema}".people')
        assert result.rows == ((0,),)
    finally:
        _drop(database, schema)


def test_failed_write_rolls_back_transaction(postgres_cluster: _Cluster) -> None:
    database = _database(postgres_cluster)
    schema = _schema_name()
    _prepare(database, schema)
    try:
        with pytest.raises(LoadError):
            _insert_duplicate(database, schema)

        with database.connect(read_only=True) as session:
            result = session.fetch_all(f'SELECT count(*) FROM "{schema}".people')
        assert result.rows == ((0,),)
    finally:
        _drop(database, schema)


def test_statement_timeout_is_enforced(postgres_cluster: _Cluster) -> None:
    database = PostgresDatabase(
        PostgresConfig(
            dsn=postgres_cluster.dsn,
            sslmode="disable",
            statement_timeout_ms=100,
        )
    )

    with (
        pytest.raises(IngestionError) as captured,
        database.connect(read_only=True) as session,
    ):
        session.fetch_all("SELECT pg_sleep(1)")

    assert captured.value.code == "DATABASE_READ_FAILED"
    assert captured.value.context.get("sqlstate") == "57014"


def _require_tls(cluster: _Cluster) -> Path:
    if cluster.cert_path is None:
        pytest.skip("OpenSSL is not available to create a test certificate")
    return cluster.cert_path


def test_tls_require_connects(postgres_cluster: _Cluster) -> None:
    _require_tls(postgres_cluster)
    database = _database(postgres_cluster, sslmode="require")

    with database.connect(read_only=True) as session:
        result = session.fetch_all("SELECT 1")

    assert result.rows == ((1,),)


def test_tls_verify_full_connects_with_root_certificate(
    postgres_cluster: _Cluster,
) -> None:
    cert_path = _require_tls(postgres_cluster)
    database = PostgresDatabase(
        PostgresConfig(
            dsn=postgres_cluster.dsn,
            sslmode="verify-full",
            sslrootcert=str(cert_path),
        )
    )

    with database.connect(read_only=True) as session:
        result = session.fetch_all("SELECT 1")

    assert result.rows == ((1,),)


def test_tls_verify_full_rejects_untrusted_certificate(
    postgres_cluster: _Cluster,
) -> None:
    _require_tls(postgres_cluster)
    database = _database(postgres_cluster, sslmode="verify-full")

    with pytest.raises(IngestionError) as captured, database.connect(read_only=True):
        pass

    assert captured.value.code == "DATABASE_READ_FAILED"


def test_tls_require_is_enforced_without_server_tls(
    postgres_cluster: _Cluster,
) -> None:
    if postgres_cluster.cert_path is not None:
        pytest.skip("test cluster has TLS enabled")
    database = _database(postgres_cluster, sslmode="require")

    with pytest.raises(IngestionError) as captured, database.connect(read_only=True):
        pass

    assert captured.value.code == "DATABASE_READ_FAILED"
