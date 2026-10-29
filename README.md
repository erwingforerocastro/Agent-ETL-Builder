# Agent ETL Builder

Local-first agent that builds validated ETL pipelines from a structured request or a
source-only assessment.

**Status:** FND-1, ST-1, REG-1, PLN-1, EXE-1, WF-1, DB-1, and API-1 complete. Five
transformations are registered in the versioned allowlist, structured plans are validated
before execution, and the bounded run workflow handles intake, approval, execution, retries,
cancellation, and cleanup. The FastAPI run contract exposes the workflow with background
execution. PostgreSQL connectivity is available through a psycopg-backed adapter. The sandbox
is an in-process guard; OS-level isolation remains deferred. Additional transformation batches
remain in progress.

## Architecture

The project follows the Dependency Rule. Source dependencies point inward:

```text
interfaces -> application -> domain
infrastructure -> application -> domain
main (composition root) -> interfaces + infrastructure
```

- `domain/`: enterprise rules and entities. No frameworks or infrastructure imports.
- `application/`: use cases, ports, validation policy, registry policy, and inward-facing DTOs.
- `infrastructure/`: framework, persistence, serialization, filesystem, sandbox, and logging adapters.
- `interfaces/`: FastAPI routes and request/response schemas.
- `main.py`: composition root; the only place that wires concrete adapters.

`tests/architecture/test_dependency_rule.py` enforces the layer direction.

## Requirements

- Python 3.12+
- `uv` for environment and dependency management

## Setup

```powershell
uv sync
```

## Run

```powershell
uv run uvicorn --app-dir src main:app --reload
```

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

Expected response:

```json
{"status":"ok","service":"agent-etl-builder","version":"0.1.0"}
```

OpenAPI docs are available at `http://127.0.0.1:8000/docs`.

## Quality checks

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
```

Format files with:

```powershell
uv run ruff format .
```

The test command enforces at least 80% coverage for the `src/` source tree.

## Configuration

Settings come from environment variables:

| Variable | Default | Values |
|---|---|---|
| `AGENT_ETL_SERVICE_NAME` | `agent-etl-builder` | Non-blank string |
| `AGENT_ETL_ENVIRONMENT` | `local` | `local`, `test`, `production` |
| `AGENT_ETL_APPROVAL_TIMEOUT_SECONDS` | `300` | Positive number |
| `AGENT_ETL_CLEANUP_POLICY` | `cleanup` | `cleanup`, `retain` |
| `AGENT_ETL_MAX_REQUEST_BYTES` | `1000000` | Positive integer |
| `AGENT_ETL_DATABASE_URL` | unset | Optional PostgreSQL DSN |
| `AGENT_ETL_DATABASE_SSLMODE` | `prefer` | `disable`, `allow`, `prefer`, `require`, `verify-ca`, `verify-full` |
| `AGENT_ETL_DATABASE_SSLROOTCERT` | unset | Optional CA certificate path for `verify-ca`/`verify-full` |
| `AGENT_ETL_DATABASE_CONNECT_TIMEOUT_SECONDS` | `10` | Positive integer |
| `AGENT_ETL_DATABASE_STATEMENT_TIMEOUT_MS` | `30000` | Positive integer |
| `AGENT_ETL_DATABASE_APPLICATION_NAME` | `agent-etl-builder` | Non-blank string |
| `AGENT_ETL_API_KEY` | unset | Optional API key for `/runs` |

Copy `.env.example` values into your shell or a local `.env` loader. Never commit `.env`
files or secrets.

## State persistence

V1 uses the process-local `InMemoryRunCheckpoint` adapter for run state. Each run snapshot is
saved after every transition, but the snapshot is lost when the process stops.

- A run is bound to one process; multiple workers do not share run state.
- V1 has no cross-restart resume.
- Plans, lineage, and run artifacts must be persisted separately from run checkpoints.
- The LangGraph `InMemorySaver` factory remains available for future graph-based workflows
  but is not wired into the application composition root.
- A persistent PostgreSQL checkpointer is deferred to a later version.

## PostgreSQL connectivity

`PostgresDatabase` opens transaction-scoped sessions through `psycopg`. It is wired lazily in
the composition root when `AGENT_ETL_DATABASE_URL` is set; no connection is opened at startup.

- All values use psycopg parameters; identifiers and SQL text remain the caller's
  responsibility. Ingestion and loading modules will build and validate those statements.
- Read-only sessions execute `SET TRANSACTION READ ONLY`; writable sessions commit on success
  and roll back on any exception.
- `statement_timeout` is applied per transaction, and connection attempts use the configured
  connect timeout and application name.
- TLS is controlled by `AGENT_ETL_DATABASE_SSLMODE`. Use `verify-full` with
  `AGENT_ETL_DATABASE_SSLROOTCERT` in production; `prefer` is the local-development default.
- Driver errors are wrapped as `IngestionError` (`DATABASE_READ_FAILED`) or `LoadError`
  (`DATABASE_WRITE_FAILED`) with a stable code, SQLSTATE, and no DSN, SQL text, or parameter
  values.

Integration tests start a temporary PostgreSQL cluster and skip when server binaries are not
available. Set `AGENT_ETL_TEST_PG_BIN` to a PostgreSQL `bin` directory to select a specific
installation. TLS tests generate a short-lived self-signed certificate with OpenSSL; set
`AGENT_ETL_TEST_OPENSSL` when OpenSSL is not on `PATH`.

## Implemented transformations

The first batch lives in `src/infrastructure/transformations/`. Each function returns a
new DataFrame, validates its columns, preserves the input, and raises
`TransformationError` with stable metadata.

| Function | Behavior |
|---|---|
| `drop_duplicate_rows` | Drops duplicates by all or selected columns; keeps first or last. |
| `drop_empty_rows` | Drops rows whose selected values are all null or blank text. |
| `trim_whitespace` | Trims leading, trailing, or both whitespace styles in text columns. |
| `standardize_column_names` | Produces collision-free snake_case names with case policy. |
| `cast_column` | Casts one column to string, integer, or float with raise/coerce modes. |

These modules are registered in registry version `1.0.0`. The allowlist policy lives in
`src/application/registry/specs.py`, concrete pandas callables are bound in
`src/infrastructure/registry/bindings.py`, and metadata is exposed through
`src/application/ports/module_registry.py`.

## Module registry

The registry is a static allowlist; it never imports module paths supplied by a user or
model. At startup it derives input metadata from each callable signature and validates:

- names, versions, module paths, and duplicate entries;
- required/default inputs and declared constraints;
- examples against input names, required values, types, and enums;
- return annotations and declared dependencies;
- exact registry/module versions at lookup time.

Any drift raises `RegistryError` and prevents the application from starting.

## Plan validation

Structured plans use a strict Pydantic schema (`extra="forbid"`) in
`src/infrastructure/validation/plan_schema.py`. The schema is an ingress adapter: it
translates JSON into domain entities, while the policy checks live in
`src/application/validation/`. `PlanValidator` then checks, in order:

1. schema, mode, and step identifiers;
2. registry allowlist and assessment read-only rules;
3. required, optional, unknown, and pipeline-managed arguments, including types and enums;
4. workspace-confined paths (traversal, absolute paths, symlinks, Windows reserved names,
   control characters, and overlong paths);
5. step count, chunk size, and serialized plan size;
6. unsafe code, raw SQL, and embedded credentials;
7. approval for writes, DDL, destructive transformations, and secret-bearing operations.

`src/application/validation/plan_validator.py` validates domain plans and has no Pydantic
or filesystem dependency. `src/infrastructure/validation/plan_validator.py` is the
JSON-facing facade: it accepts either an `ExecutionPlan` or a JSON-compatible payload,
parses the payload, and delegates inward. Filesystem path inspection is isolated behind
`WorkspaceProbePort` and implemented by `FilesystemWorkspaceProbe`.

Every failure raises `PlanValidationError` with a stable code and sanitized context.
Validation checks are independent `PlanValidationCheck` implementations assembled by
`build_default_checks`; callers can inject a custom pipeline with
`PlanValidator(..., checks=(...))`.

## Sandbox execution

`ExecutePlanUseCase` validates the plan before calling any step. `SandboxExecutor` then
runs each allowlisted callable under a serialized guard:

- file reads and writes are confined to the workspace; read-only runtime paths needed by
  Python and pandas are allowed;
- network connections and name resolution are denied by default;
- wall-clock time is bounded, and the traced Python memory peak is checked;
- the workspace is the execution working directory and the previous directory is restored.

The guard is an in-process Python control, not an OS-level container. It does not isolate
native extensions, CPU quotas, or code that bypasses the patched Python APIs; those remain
deployment-level hardening items.

## Run workflow

`RunWorkflow` is a plain application state machine; persistence and external effects are
injected ports. One instance handles one run and checkpoints every transition.

- Plan intake goes through `PlanIntakePort`. A deterministic adapter is available for tests
  and local development.
- Validation and clarification are bounded to 3 attempts.
- Approval is derived from registry policy, not trusted from the plan's own flag alone.
  The default timeout is 300 seconds.
- Execution retries at most twice with bounded exponential backoff; only retryable errors
  are retried.
- Cancellation is checked at approval, step, and retry boundaries.
- Non-success terminal paths run cleanup according to `AGENT_ETL_CLEANUP_POLICY`
  (`cleanup` or `retain`).

Run state, API results, and logs are process-local. They do not survive a restart in v1.

Configuration:

```text
AGENT_ETL_APPROVAL_TIMEOUT_SECONDS=300
AGENT_ETL_CLEANUP_POLICY=cleanup
AGENT_ETL_MAX_REQUEST_BYTES=1000000
# AGENT_ETL_API_KEY=replace-me
```

## HTTP API

The API is created in `src/main.py` and exposes the run contract:

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/runs` | Create a run from a message and/or structured plan. Returns `201` with run state. |
| `GET` | `/runs/{run_id}` | Current status, plan, questions, result, cleanup, and next action. |
| `POST` | `/runs/{run_id}/approve` | Approve or reject: `{"approved": true\|false}`. |
| `POST` | `/runs/{run_id}/cancel` | Request cancellation at the next safe boundary. |
| `GET` | `/runs/{run_id}/logs` | Structured lifecycle events for the run. |
| `GET` | `/health` | Liveness and service metadata. |

Example:

```powershell
$body = @{
  message = "Assess input.csv"
  plan = @{
    plan_version = "1.0"
    mode = "assessment"
    run_id = "1729850000000-a1b2c3d4"
    name = "assess_input"
    description = "Assess the input"
    source = @{ operation = "read_csv"; params = @{ path = "input.csv" } }
    transformations = @()
    destination = $null
    chunking = @{ enabled = $true; size = 1000 }
    on_error = "fail_fast"
    approval_required = $false
  }
} | ConvertTo-Json -Depth 6

Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/runs `
  -ContentType application/json -Body $body
```

Behavior notes:

- Runs that are ready execute on a background thread pool; API requests never wait for
  execution. Approval-gated runs execute after `POST /runs/{run_id}/approve`.
- Message-only requests currently return `awaiting_clarification` because no plan builder is
  configured. Submit a structured `plan` to execute.
- Plans are schema-parsed, validated, and only then used to create a run. Invalid plans return
  `400`; unknown runs return `404`; state conflicts return `409`. Pipeline plans containing
  writes or destructive steps must set `approval_required: true`; the workflow still derives
  the final approval requirement from registry policy.
- Errors use `{code, message, retryable, details?}` and never expose internal stack traces.
- Request bodies are limited by `AGENT_ETL_MAX_REQUEST_BYTES`. If `AGENT_ETL_API_KEY` is set,
  `/runs` requires `X-API-Key`; `/health` remains public.
- Results expose status, output count, data availability, and sanitized step errors; raw
  DataFrames are not serialized into API responses. Assessment/draft-plan payloads and usage
  metrics arrive with ASM-1/PRF-1/MON-1.
- Logs are process-local lifecycle events until MON-1 adds transform CSV and execution JSONL
  logging. Rate limiting remains a deployment-level control for production exposure.

## Security baseline

- Generated code is never executed. The interpreter runs only validated plans through
  allowlisted registry functions.
- Secrets belong in environment variables or a secret store and must be redacted from
  logs, errors, prompts, reports, and artifacts.
- Source data and user context are untrusted; profiling artifacts are read-only.
- API key authentication and request-size limits are available; rate limiting and production
  auth hardening are required before broad exposure.

See `documents/security.txt` for the full strategy and `documents/requirements_agent.txt`
for agent behavior.

## Project layout

```text
src/
  domain/
  application/
    ports/
    registry/
    use_cases/
    validation/
  infrastructure/
  interfaces/
  main.py
  COMPONENTS.md
tests/
  architecture/
  integration/
  unit/
documents/
```

## Roadmap

`EXE-1`, `WF-1`, `DB-1`, and `API-1` are complete: plans are validated before execution, the
sandbox enforces workspace, network, timeout, and memory limits, the workflow bounds
clarification, approval, retries, cancellation, and cleanup, PostgreSQL sessions are
parameterized and transaction-scoped, and the FastAPI run contract executes runs in the
background. The next P1 backlog item is `ING-1` (ingestion adapters). Additional `TRN-0`
transformation batches remain in progress.
