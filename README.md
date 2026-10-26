# Agent ETL Builder

Local-first agent that builds validated ETL pipelines from a structured request or a
source-only assessment.

**Status:** FND-1 project skeleton complete. ETL modules, plan validation, the LangGraph
workflow, and MySQL adapters are not implemented yet.

## Architecture

The project follows the Dependency Rule. Source dependencies point inward:

```text
interfaces -> application -> domain
infrastructure -> application -> domain
main (composition root) -> interfaces + infrastructure
```

- `domain/`: enterprise rules and entities. No frameworks or infrastructure imports.
- `application/`: use cases, ports, and inward-facing DTOs.
- `infrastructure/`: framework, persistence, model, sandbox, and logging adapters.
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

## Security baseline

- Generated code is never executed. The future interpreter will run only validated plans
  through allowlisted registry functions.
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

The next backlog item is `ST-1`: wire the LangGraph local in-memory checkpointer and prove
process-local restart behavior.
