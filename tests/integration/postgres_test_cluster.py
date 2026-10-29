"""Temporary PostgreSQL cluster helpers for integration tests."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import psycopg
import pytest


@dataclass(frozen=True, slots=True)
class PostgresCluster:
    dsn: str
    cert_path: Path | None


def _exe(name: str) -> str:
    return f"{name}.exe" if os.name == "nt" else name


def _has_server_binaries(candidate: Path) -> bool:
    return all((candidate / _exe(name)).exists() for name in ("initdb", "postgres", "pg_ctl"))


def find_pg_bin() -> Path | None:
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


@contextmanager
def running_postgres_cluster(data_dir: Path) -> Iterator[PostgresCluster]:
    bin_dir = find_pg_bin()
    if bin_dir is None:
        pytest.skip("PostgreSQL server binaries are not available")

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
        yield PostgresCluster(dsn=dsn, cert_path=cert_path)
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


__all__ = ["PostgresCluster", "find_pg_bin", "running_postgres_cluster"]
