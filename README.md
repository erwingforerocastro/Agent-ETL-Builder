# Agent ETL Builder

Local-first agent that builds validated ETL pipelines from a structured request or a
source-only assessment.

**Status:** FND-1, ST-1, REG-1, and PLN-1 complete. Five transformations are registered in
the versioned allowlist, and structured plans are validated before execution. The bounded
LangGraph workflow, full sandbox limit enforcement, and PostgreSQL adapters are not implemented
yet.

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

Copy `.env.example` values into your shell or a local `.env` loader. Never commit `.env`
files or secrets.

## State persistence

V1 uses a single LangGraph `InMemorySaver` created in `src/main.py` and exposed through
`app.state.checkpointer`. Its lifetime is the current process.

- State persists across turns and requests that use the same `thread_id`.
- State is lost when the process stops; v1 has no cross-restart resume.
- Each application process or worker has isolated state; do not run multiple workers when
  conversation continuity is required.
- Plans, lineage, and run artifacts must be persisted separately from checkpoints.
- A persistent PostgreSQL checkpointer is deferred to a later version.

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
Validation checks are independent `PlanCheck` implementations assembled by
`build_default_checks`; callers can inject a custom pipeline with
`PlanValidator(..., checks=(...))`.

## Security baseline

- Generated code is never executed. The interpreter runs only validated plans through
  allowlisted registry functions.
- Secrets belong in environment variables or a secret store and must be redacted from
  logs, errors, prompts, reports, and artifacts.
- Source data and user context are untrusted; profiling artifacts are read-only.
- API authentication, request-size limits, and rate limits are required before production
  exposure.

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
tests/
  architecture/
  integration/
  unit/
documents/
```

## Roadmap

The next P0 backlog item is `EXE-1`: complete interpreter and sandbox enforcement, including
timeout, memory, filesystem, and network limits with tests. Additional `TRN-0` transformation
batches remain in progress.
