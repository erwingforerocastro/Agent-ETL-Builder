"""Manual beta smoke test for the Agent ETL Builder HTTP API.

Run this from the repository root while the API is running:

    uv run python scripts/beta_smoke.py

The script exercises three flows:
1. natural-language request -> generated plan -> approval -> JSON output;
2. clarification -> follow-up message -> approval -> JSON output;
3. structured plan -> approval -> CSV output.

It uses only the Python standard library.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

TERMINAL = {"succeeded", "failed", "rejected", "cancelled", "timed_out"}
SOURCE = "examples/beta/input.csv"
JSON_OUTPUT = "beta_output.json"
CSV_OUTPUT = "beta_output.csv"
ROOT = Path.cwd()


class SmokeError(RuntimeError):
    """A smoke-test assertion or API call failed."""


def _request(
    args: argparse.Namespace,
    method: str,
    path: str,
    payload: dict[str, object] | None = None,
) -> tuple[int, dict[str, Any]]:
    url = f"{args.base_url.rstrip('/')}{path}"
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if args.api_key:
        headers["X-API-Key"] = args.api_key
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=args.request_timeout) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"code": "HTTP_ERROR", "message": raw}
        return exc.code, parsed


def _require_ok(
    args: argparse.Namespace,
    method: str,
    path: str,
    payload: dict[str, object] | None = None,
    *,
    expected: int = 201,
) -> dict[str, Any]:
    status, body = _request(args, method, path, payload)
    if status != expected:
        raise SmokeError(f"{method} {path} returned {status}: {body}")
    return body


def _wait(args: argparse.Namespace, run_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + args.timeout
    last_status: str | None = None
    while True:
        status, body = _request(args, "GET", f"/runs/{run_id}")
        if status != 200:
            raise SmokeError(f"GET /runs/{run_id} returned {status}: {body}")
        current = str(body.get("status"))
        if current != last_status:
            print(f"  run {run_id}: {current}")
            last_status = current
        if current in TERMINAL:
            return body
        if time.monotonic() > deadline:
            raise SmokeError(f"run {run_id} did not finish within {args.timeout}s")
        time.sleep(1)


def _handle_run(
    args: argparse.Namespace,
    body: dict[str, Any],
    *,
    source: str,
    destination: str,
) -> dict[str, Any]:
    run_id = str(body["run_id"])
    clarifications = 0
    while True:
        status = body.get("status")
        if status == "awaiting_clarification":
            clarifications += 1
            questions = body.get("questions") or []
            print(f"  clarification {clarifications}: {questions}")
            if clarifications > 3:
                raise SmokeError(f"run {run_id} asked too many questions")
            body = _require_ok(
                args,
                "POST",
                f"/runs/{run_id}/messages",
                {
                    "message": (
                        "Use the provided source and destination. "
                        "Use only columns that exist in the source; do not invent columns."
                    ),
                    "source": source,
                    "destination": destination,
                },
                expected=200,
            )
            continue
        if status == "awaiting_approval":
            body = _require_ok(
                args,
                "POST",
                f"/runs/{run_id}/approve",
                {"approved": True},
                expected=200,
            )
        if body.get("status") in {"ready", "running", "retrying"}:
            return _wait(args, run_id)
        if body.get("status") in TERMINAL:
            return body
        raise SmokeError(f"run {run_id} entered unexpected status {status!r}")


def _print_run_paths(run_id: str) -> None:
    print(f"  logs: logs/{run_id}.jsonl")
    print(f"  transform log: artifacts/{run_id}/transform_log.csv")


def _assert_success(body: dict[str, Any]) -> None:
    if body.get("status") != "succeeded":
        raise SmokeError(f"run failed: {body.get('status')} {body.get('error')}")


def _reset_outputs() -> None:
    for name in (JSON_OUTPUT, CSV_OUTPUT):
        path = ROOT / name
        if path.exists():
            path.unlink()


def _assert_json_output() -> None:
    path = ROOT / JSON_OUTPUT
    if not path.exists():
        raise SmokeError(f"missing output: {path}")
    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list) or len(records) != 2:
        raise SmokeError(f"unexpected JSON output: {records!r}")
    names = [record.get("name") for record in records]
    if names != ["Ada", "Bob"]:
        raise SmokeError(f"unexpected names in JSON output: {names!r}")


def _assert_csv_output() -> None:
    path = ROOT / CSV_OUTPUT
    if not path.exists():
        raise SmokeError(f"missing output: {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 2:
        raise SmokeError(f"unexpected CSV row count: {len(rows)}")
    names = [row.get("name") for row in rows]
    if names != ["Ada", "Bob"]:
        raise SmokeError(f"unexpected names in CSV output: {names!r}")


def _run_id(prefix: str) -> str:
    return f"{int(time.time() * 1_000)}-{prefix}"


def _natural_language_flow(args: argparse.Namespace) -> None:
    print("1. natural-language flow")
    _reset_outputs()
    body = _require_ok(
        args,
        "POST",
        "/runs",
        {
            "run_id": _run_id("nl"),
            "message": (
                "Remove duplicate rows, trim whitespace, and save the result as JSON."
            ),
            "source": SOURCE,
            "destination": JSON_OUTPUT,
        },
    )
    final = _handle_run(args, body, source=SOURCE, destination=JSON_OUTPUT)
    _assert_success(final)
    _assert_json_output()
    _print_run_paths(str(final["run_id"]))


def _clarification_flow(args: argparse.Namespace) -> None:
    print("2. clarification flow")
    _reset_outputs()
    body = _require_ok(
        args,
        "POST",
        "/runs",
        {
            "run_id": _run_id("clarify"),
            "message": (
                "Remove duplicate rows, trim whitespace, and save the result as JSON."
            ),
        },
    )
    if body.get("status") != "awaiting_clarification":
        raise SmokeError(f"expected clarification, got {body.get('status')}")
    final = _handle_run(args, body, source=SOURCE, destination=JSON_OUTPUT)
    _assert_success(final)
    _assert_json_output()
    _print_run_paths(str(final["run_id"]))


def _structured_flow(args: argparse.Namespace) -> None:
    print("3. structured-plan flow")
    _reset_outputs()
    template = json.loads(
        (ROOT / "examples/beta/plan.json").read_text(encoding="utf-8")
    )
    run_id = _run_id("structured")
    template["run_id"] = run_id
    template["destination"]["params"]["path"] = CSV_OUTPUT
    body = _require_ok(
        args,
        "POST",
        "/runs",
        {"message": "Run the structured smoke plan", "plan": template},
    )
    if body.get("status") != "awaiting_approval":
        raise SmokeError(f"expected approval, got {body.get('status')}")
    final = _handle_run(args, body, source=SOURCE, destination=CSV_OUTPUT)
    _assert_success(final)
    _assert_csv_output()
    _print_run_paths(str(final["run_id"]))


def _health(args: argparse.Namespace) -> None:
    status, body = _request(args, "GET", "/health")
    if status != 200:
        raise SmokeError(f"/health returned {status}: {body}")
    print(f"health: {body.get('status')} {body.get('version')}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("AGENT_ETL_BASE_URL", "http://127.0.0.1:8000"),
    )
    parser.add_argument("--api-key", default=os.getenv("AGENT_ETL_API_KEY"))
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--request-timeout", type=float, default=180.0)
    parser.add_argument(
        "--skip-nl",
        action="store_true",
        help="skip the two natural-language flows",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        _health(args)
        if not args.skip_nl:
            _natural_language_flow(args)
            _clarification_flow(args)
        _structured_flow(args)
    except (SmokeError, OSError, ValueError, KeyError) as exc:
        print(f"SMOKE FAILED: {exc}", file=sys.stderr)
        return 1
    print("SMOKE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
