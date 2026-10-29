# Changelog

## 0.2.0b1 - 2026-10-29

First usable agent beta.

### Added

- Natural-language run intake through a local Ollama model.
- Registry-derived JSON schema for transformation drafts.
- Deterministic source/destination binding by file extension.
- Bounded repair of invalid plans using validation errors.
- `POST /runs/{run_id}/messages` for clarification follow-ups.
- Bounded source schema inspection so the model sees real column names and dtypes.
- Execution JSONL logs at `logs/<run_id>.jsonl`.
- Transform CSV logs at `artifacts/<run_id>/transform_log.csv`.
- Secret and credential redaction for monitoring events.
- Stderr fallback when monitoring files cannot be written.
- Preserved transform logs when failed-run artifacts are cleaned up.
- `scripts/beta_smoke.py` and `examples/beta/` fixtures.
- Golden plan-shape tests and an optional live Ollama evaluation.

### Changed

- `save_csv`, `save_json`, `save_jsonl`, and `save_parquet` remain atomic overwrite writers.
- `RunLogEntry` now carries a structured `error` object.
- `ExecutePlanUseCase` emits source, step, and destination monitoring events.
- Direct plan-synthesis failures map to `503`; synthesis failures during intake terminate the
  run with the same stable error code.

### Known limitations

- Run state, conversations, and logs are process-local; restart loses active runs.
- Plan generation is synchronous and usually takes 15-45 seconds with `llama3.1:8b`.
- Source schema is sampled from the first 50 rows, not a full scan.
- Column existence and dtype compatibility are checked during execution, not plan validation.
- PostgreSQL remains adapter-only; network access is denied during registry execution.
- No web UI, authentication hardening, rate limiting, or persistent checkpoints.
- Approval timeout is not enforced for API-scheduled runs left in `awaiting_approval`.
