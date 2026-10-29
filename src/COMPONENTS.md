# Agent ETL Builder - Component Map

This document explains what each component does, which layer owns it, and how the pieces
are connected at runtime. It is a map, not a specification; the authoritative behavior lives
in the code and tests.

## 1. The dependency rule

```text
interfaces ----> application ----> domain
infrastructure -> application ----> domain
main (composition root) ----> interfaces + infrastructure
```

- `domain/` contains enterprise rules and value objects. It imports no frameworks and no
  infrastructure.
- `application/` contains use cases, ports, and policy. It imports `domain/` only.
- `infrastructure/` contains mechanisms: pandas, PostgreSQL sessions, files, sandbox,
  serialization, clocks, persistence adapters.
- `interfaces/` contains FastAPI routes and response schemas.
- `main.py` is the only place that constructs concrete adapters and wires them together.

The architecture test `tests/architecture/test_dependency_rule.py` enforces this direction
and rejects import cycles.

## 2. Composition root (`src/main.py`)

`main.py` builds one object graph at process start:

```text
Settings.from_env()
  |
  +--> PostgresDatabase(PostgresConfig(...)) when database_url is set
  |       -> lazy PostgreSQL sessions (no startup connection)
  |
  +--> build_module_registry(MODULE_SPECS, MODULE_FUNCTIONS)
  |       -> ModuleRegistry (validated snapshot + allowlisted callables)
  |
  +--> FilesystemWorkspaceProbe(workspace)
  +--> CanonicalPlanSizer()
  |       -> PlanValidator (application + infrastructure facade)
  |
  +--> SandboxExecutor(SandboxLimits(), workspace)
  +--> RegistryStepRunner(module_registry, sandbox)
  |       -> ExecutePlanUseCase(step_runner, plan_validator)
  |
  +--> SystemClock()
  +--> InMemoryRunCheckpoint()
  +--> InMemoryApprovalGateway(clock)
  +--> FilesystemCleanup(workspace / "artifacts")
  +--> CanonicalPlanHasher()
  +--> WorkflowLimits(
          approval_timeout_seconds=settings.approval_timeout_seconds,
          cleanup_policy=settings.cleanup_policy,
       )
  |
  +--> RunWorkflowFactory(shared workflow adapters)
  +--> SubmittedPlanIntakeFactory()
  +--> PydanticPlanParser()
  +--> InMemoryRunLog()
  +--> ThreadPoolRunScheduler(max_workers=4)
  |       -> RunManager(
               workflow_factory, plan_parser, validator, intake_factory,
               checkpoints, run_log, scheduler, clock, cancellation_factory,
             )
  |
  +--> create_app(
          service_name, version,
          run_manager=run_manager,
          max_request_bytes=settings.max_request_bytes,
          api_key=settings.api_key,
          shutdown_callbacks=(run_scheduler.shutdown,),
       )
         -> FastAPI + health router + run router + error handlers
```

A `RunWorkflow` instance is intentionally **not** shared between runs: it remembers one
`run_id` and routes one lifecycle. `RunManager` creates a fresh workflow, a fresh
cancellation token, and a fresh intake adapter for each run, then schedules execution when
the run becomes `ready`. `app.state.database` exposes the optional database adapter for
later ingestion/loading wiring.

## 3. Domain (`src/domain/`)

### Plan entities (`entities/plan.py`)

| Component | Purpose |
|---|---|
| `PlanSource` | Read operation and its parameters. |
| `PlanDestination` | Write operation and its parameters. |
| `PlanTransformation` | One step with a unique `step_id`, operation, and parameters. |
| `PlanChunking` | Chunking flag and positive chunk size. |
| `ExecutionPlan` | Validated plan aggregate. Enforces mode-specific source/destination rules, unique step ids, and non-blank fields. |

### Run entities (`entities/run.py`)

| Component | Purpose |
|---|---|
| `RunStatus` | Lifecycle state. `terminal` tells callers whether the run is finished. |
| `ApprovalState` | Approval decision attached to a run. |
| `CleanupPolicy` | `cleanup` removes partial artifacts; `retain` keeps them. |
| `WorkflowLimits` | Clarification budget, retry budget, approval timeout, backoff, cleanup policy. |
| `PlanRequest` | User-facing intake request (`run_id`, `thread_id`, message, mode, source, destination). |
| `PlanIntakeResult` | Either a proposed plan or clarification questions/missing inputs/reason. |
| `Run` | Immutable run snapshot. `Run.create` and `Run.transition` enforce the allowed state graph and field invariants. |

### Registry entities (`entities/registry.py`)

| Component | Purpose |
|---|---|
| `ConstraintKind` / `Constraint` | Typed input policy: non-empty, column name(s), existing column, text columns, path, enum. |
| `ModuleInput` / `ModuleOutput` | Declared input/output metadata derived from callables. |
| `ModuleMetadata` | One allowlisted module: version, module path, function, inputs, output, side effects, examples, security notes. |
| `RegistrySnapshot` | Immutable versioned collection of modules. |

### Errors (`errors.py`)

`EtlError` is the shared base. It carries a stable `code`, sanitized `message`, `module`,
`retryable` flag, and structured `context`. Subclasses cover transformation, ingestion, load,
registry, plan validation, sandbox, and workflow failures. Workflow-specific errors include
`RUN_NOT_FOUND`, `RUN_ALREADY_EXISTS`, `RUN_INVALID_STATE`, `RUN_CANCELLED`,
`RUN_CLARIFICATION_EXHAUSTED`, `RUN_APPROVAL_REJECTED`, `RUN_APPROVAL_TIMEOUT`,
`RUN_PLAN_STALE`, `RUN_EXECUTION_FAILED`, `RUN_INTAKE_FAILED`, and `RUN_APPROVAL_FAILED`.

### Shared invariant helpers (`entities/_validation.py`)

Small helpers used by multiple entities: `require_text`, `require_non_negative_int`,
`require_positive_int`, and `require_aware_datetime`. They keep entity constructors
consistent without duplicating checks.

## 4. Application ports (`src/application/ports/`)

Ports are the seams between policy and mechanisms. Production adapters are listed in the
last column.

| Port | Responsibility | Adapter |
|---|---|---|
| `PlanIntakePort` | Turn a request into a plan or clarification request. | `SubmittedPlanIntake` (API), `DeterministicPlanIntake` (tests) |
| `PlanIntakeFactoryPort` | Create one intake adapter per run. | `SubmittedPlanIntakeFactory` |
| `PlanParserPort` | Parse an untrusted JSON-compatible plan payload. | `PydanticPlanParser` |
| `PlanValidatorPort` | Validate a domain plan. | `infrastructure.validation.plan_validator.PlanValidator` |
| `ModuleRegistryReadPort` | Read registry snapshots and metadata. | `ModuleRegistry` |
| `ModuleFunctionResolverPort` | Resolve an operation name to its allowlisted callable. | `ModuleRegistry` |
| `ModuleRegistryPort` | Combined read + callable contract for consumers that need both. | `ModuleRegistry` |
| `PlanHasherPort` | Stable plan hash for stale-plan detection. | `CanonicalPlanHasher` |
| `PlanSizerPort` | Serialized plan size for limits. | `CanonicalPlanSizer` |
| `WorkspaceProbePort` | Inspect workspace paths without exposing filesystem details. | `FilesystemWorkspaceProbe` |
| `ExecutionPort` | Execute a validated plan with optional cancellation. | `ExecutePlanUseCase` |
| `StepRunnerPort` | Run source/transformation/destination steps. | `RegistryStepRunner` |
| `SandboxRunnerPort` | Run one callable under sandbox guards. | `SandboxExecutor` |
| `RunCheckpointPort` | Save and load run snapshots. | `InMemoryRunCheckpoint` |
| `ApprovalPort` | Request and record human approval. | `InMemoryApprovalGateway` |
| `CancellationTokenPort` | Signal and observe cancellation. | `EventCancellationToken` |
| `ClockPort` | Aware time, monotonic time, and sleep. | `SystemClock` |
| `CleanupPort` | Remove or retain partial run artifacts. | `FilesystemCleanup` |
| `RunLogPort` | Append and read structured run events. | `InMemoryRunLog` |
| `BackgroundSchedulerPort` | Submit run work outside the request thread. | `ThreadPoolRunScheduler` |
| `DatabasePort` | Open a transaction-scoped read-only or writable session. | `PostgresDatabase` |
| `DatabaseSessionPort` | Parameterized fetch/execute/execute-many operations. | `PostgresSession` |

## 5. Plan validation (`src/application/validation/`)

The validation pipeline is assembled by `factory.build_default_checks` and executed in order
by `PlanValidator`. Each check implements `PlanValidationCheck`.

```text
ExecutionPlan
  |
  +-> SchemaValidator          version, mode, operation names, step ids, on_error
  +-> RegistryEntryValidator   allowlist lookup, assessment must be read-only
  +-> ArgumentValidator        unknown/missing/pipeline args, types, constraints
  +-> PlanPathValidator        path-like arguments anywhere in params
  +-> LimitsValidator          step count, chunk size, serialized size
  +-> SecurityValidator        code syntax, raw SQL, secrets, unsafe shapes
  +-> ApprovalValidator        approval required for writes/destructive actions
  |
  v
PlanValidationError with stable code and sanitized context
```

Key collaborators:

| Component | Purpose |
|---|---|
| `PlanValidationSettings` | One settings object for all limits, replacing a long scalar constructor. |
| `PlanValidationCheck` | Protocol for one validation pass. Custom pipelines can be injected. |
| `OperationCatalog` | Registry lookup with plan-validation errors for unknown operations. |
| `OperationSafetyPolicy` | Classifies writes/destructive operations and derives approval requirements. |
| `iter_operations` / `OperationCall` | Uniform traversal of source, transformations, and destination. |
| `PathValueValidator` | Shape, relative-path, Windows-reserved, workspace, symlink, and length checks. |
| `ArgumentValidator` | Dispatch table from `ConstraintKind` to focused constraint checkers. |

The application validator works with domain plans only. The infrastructure facade in
`infrastructure/validation/plan_validator.py` additionally accepts JSON-compatible mappings
and parses them with the strict Pydantic schema before delegating inward.

## 6. Module registry

### Policy (`src/application/registry/`)

| Component | Purpose |
|---|---|
| `specs.py` | Static allowlist: module names, versions, constraints, examples, dependencies, side effects, security notes. |
| `vocabulary.py` | Shared enum-like vocabularies used by specs and transformations. |
| `constants.py` | Registry version and output description. |
| `metadata.py` | `RegistryErrorFactory` for structured registry errors. |

### Infrastructure (`src/infrastructure/registry/`)

| Component | Purpose |
|---|---|
| `bindings.py` | Maps allowlisted operation names to concrete pandas callables and declares capability packages. |
| `validators.py` | `ModuleMetadataBuilder` inspects signatures, validates defaults/examples/dependencies, and produces `ModuleMetadata`. |
| `functions.py` | `build_snapshot` rejects duplicate names, missing callables, and unbound callables, then builds the snapshot. |
| `module_registry.py` | `ModuleRegistry` provides version-aware `get`, `require`, and `function_for` over the snapshot. |

```text
ModuleSpec + callable
        |
        v
ModuleMetadataBuilder
  - dependency available?
  - name matches callable?
  - module under approved prefix?
  - signature annotated and keyword-only after DataFrame?
  - constraints reference real inputs?
  - examples use caller inputs with valid types/enums?
  - defaults and return annotation valid?
        |
        v
ModuleMetadata ---> RegistrySnapshot ---> ModuleRegistry ---> application ports
```

## 7. Run workflow (`src/application/use_cases/`)

`RunWorkflow` is a thin facade over four focused collaborators. It owns the run id and routes
each public operation to the right stage.

| Component | Purpose |
|---|---|
| `RunWorkflow` | Public state-machine facade: `start`, `resume`, `run`, `approve`, `cancel`, `get`. |
| `RunWorkflowFactory` | Assembles one `RunWorkflow` from shared adapters for one run. |
| `RunManager` | API-facing coordinator: parses/validates plans, creates workflows and tokens, stores outcomes, schedules background execution, logs lifecycle events, and serves status/logs. |
| `RunIntakeCoordinator` | Intake, clarification/repair loop, validation, plan hashing, approval requirement, and preparation for approval/execution. |
| `RunApprovalCoordinator` | Waits for a decision, records approve/reject, and maps timeout/cancel/reject to terminal states. |
| `RunExecutionCoordinator` | Stale-plan checks, cancellation boundaries, bounded retries with backoff, and terminal execution outcomes. |
| `RunStore` | Load/save `Run` snapshots through `RunCheckpointPort`; raises `RunNotFoundError`. |
| `RunTerminator` | Enforces idempotent terminal transitions and applies the cleanup policy. |
| `RunOutcome` | Returned run plus optional execution result and cleanup result. |

### Lifecycle

```text
created
  |
  +--> awaiting_clarification --(resume)--> awaiting_clarification
  |                         \--> ready
  |                         \--> awaiting_approval
  |
  +--> ready ------------------------------> running
  +--> awaiting_approval --(approve)-------> ready
  |                     --(reject)--------> rejected
  |                     --(timeout)-------> timed_out
  |                     --(cancel)--------> cancelled
  |
  running --(retryable error)--> retrying --> running
  running --(success)---------> succeeded
  running --(failure/timeout)--> failed / timed_out
  running --(cancel)-----------> cancelled
```

### Sequence: start, approve, execute

```text
POST /runs
  |
  v
RunManager.create(command)
  - PydanticPlanParser.parse(plan payload)
  - PlanValidator.validate(plan)
  - resolve run_id/mode
  - create cancellation token + SubmittedPlanIntake
  - RunWorkflowFactory.create(...)
  |
  v
RunWorkflow.start(request) -----> RunStore.save(Run.created)
  |                                |
  |                                v
  |                           RunIntakeCoordinator
  |                             - intake.request(...)
  |                             - validate run_id/mode + PlanValidator
  |                             - hash plan
  |                             - OperationCatalog + OperationSafetyPolicy
  |                             - transition ready | awaiting_approval
  |
  +--> status ready? --> BackgroundSchedulerPort.submit(run_id, RunManager._run)
  |
  | POST /runs/{id}/approve
  v
RunApprovalCoordinator
  - ApprovalPort.decide(...)
  - transition ready on approval, rejected on rejection
  - if ready, schedule background execution
  |
  | background run()
  v
RunApprovalCoordinator.wait(...) when awaiting approval
  - ApprovalPort.request(timeout, cancellation)
  - approved -> ready; rejected -> rejected; cancelled -> cancelled; else timed_out
  |
  v
RunExecutionCoordinator
  - reject stale registry/plan/hash
  - ExecutePlanUseCase.execute(plan, cancellation)
  - retry only retryable EtlError up to WorkflowLimits.max_execution_retries
  - succeeded / failed / timed_out / cancelled
  |
  v
RunTerminator (on non-success) -> CleanupPort.apply(run_id, policy)
  |
  v
RunManager stores RunOutcome and appends run_finished to RunLogPort
```

`RunWorkflow.run()` can block while waiting for approval, so `RunManager` executes it on a
background scheduler. `RunManager` keeps the latest `RunOutcome` in process memory for API
status/result responses; `RunCheckpointPort` stores the `Run` snapshot but not the execution
result. A restart loses both. `GET /runs/{id}/logs` currently returns lifecycle events from
`RunLogPort`; transform CSV and execution JSONL logs arrive with MON-1.

## 8. Execution and sandbox

### Plan execution (`application/use_cases/execute_plan.py`)

`ExecutePlanUseCase` validates again, checks cancellation, and runs:

```text
source -> transformations (in order) -> destination
```

- `on_error="fail_fast"` raises the first transformation/destination failure.
- `on_error="continue"` records sanitized `ExecutionStepError`s and returns `partial`, or
  `failed` when the destination fails.
- Cancellation and sandbox errors are never swallowed by `on_error="continue"`.
- Results include outputs and, for assessment plans without a destination, the DataFrame.

### Step runner (`infrastructure/interpreter/registry_step_runner.py`)

`RegistryStepRunner` joins registry metadata and pandas plumbing:

- `run_source`: passes an empty DataFrame only when the module declares a pipeline input.
- `run_transformation` / `run_destination`: pass the current data as the first argument.
- Every call goes through `SandboxRunnerPort` (production: `SandboxExecutor`).

### Sandbox (`infrastructure/sandbox/`)

| Component | Purpose |
|---|---|
| `SandboxExecutor` | Serializes execution, sets the workspace as cwd, installs guards, checks memory, and bounds wall-clock time. |
| `guards._WorkspaceFilesystemGuard` | Patches `builtins.open`, `io.open`, and relevant `os` functions; reads are confined to workspace plus runtime roots, writes/mutations to workspace only. |
| `guards.network_guard` | Blocks socket creation/connect/bind/listen/send and name resolution. |
| `executor.timeout_context` | Chooses SIGALRM/setitimer on Unix main threads or a watchdog thread plus CPython async exception elsewhere. |
| `executor.memory_guard` | Checks the traced Python peak against `memory_mb`. |
| `limits.SandboxLimits` | Timeout, memory, network, and workspace-only settings. CPU quotas require OS isolation and are intentionally not exposed. |
| `errors.py` | `SandboxTimeoutError`, `SandboxMemoryError`, and `SandboxViolationError` with stable codes. |

The sandbox is an in-process defense-in-depth guard, not a container. It does not stop native
extensions, code that bypasses the patched Python APIs, hard OOM kills, CPU quotas, or process
cleanup. Those are deployment-level hardening items.

## 9. Infrastructure adapters

| Adapter | Purpose |
|---|---|
| `approval/in_memory.py` | Condition-based in-process approval gateway with timeout and cancellation polling. |
| `cancellation.py` | `EventCancellationToken` backed by `threading.Event`. |
| `cleanup/filesystem.py` | Removes or retains `artifacts/<run_id>` with path-safety checks. |
| `clock.py` | `SystemClock` provides aware UTC time, monotonic time, and sleep. |
| `config/settings.py` | Environment-backed settings, including approval timeout, cleanup policy, API key, request-size limit, and PostgreSQL DSN/TLS/timeouts. |
| `database/config.py` | `PostgresConfig` and SSL mode/root-certificate validation without driver imports. |
| `database/postgres.py` | `PostgresDatabase` / `PostgresSession`: psycopg sessions, TLS, timeouts, parameterized SQL, commit/rollback, sanitized driver errors. |
| `interpreter/registry_step_runner.py` | Registry function resolution + sandbox execution + DataFrame plumbing. |
| `logging/run_log.py` | Process-local structured lifecycle log. |
| `planning/deterministic.py` | Deterministic `PlanIntakePort` fake for tests and local development. |
| `planning/submitted.py` | `SubmittedPlanIntake` / factory for API-supplied plans. |
| `scheduling/thread_pool.py` | Bounded background thread-pool scheduler for run execution. |
| `state/run_checkpoint.py` | Process-local run snapshots. |
| `state/checkpointing.py` | LangGraph `InMemorySaver` factory for future graph workflows; not wired into the app. |
| `validation/path_probe.py` | Filesystem workspace inspection for path validation. |
| `validation/plan_parser.py` | `PydanticPlanParser` adapter for `PlanParserPort`. |
| `validation/plan_schema.py` | Strict Pydantic schema that parses JSON-compatible payloads into domain entities. |
| `validation/plan_serialization.py` | Canonical plan serialization used by hashing and sizing. |
| `validation/plan_hasher.py` | `CanonicalPlanHasher` (SHA-256 over canonical serialization). |
| `validation/plan_sizer.py` | `CanonicalPlanSizer` (serialized size). |
| `validation/plan_validator.py` | JSON-facing validation facade over the application validator. |
| `transformations/` | Deterministic pandas transformations registered in the allowlist. |
| `ingestion/csv.py` | CSV source adapter. |
| `loaders/csv.py` | CSV destination adapter. |

### PostgreSQL sessions (`infrastructure/database/`)

```text
DatabasePort.connect(read_only=...)
  |
  +-> psycopg.connect(dsn, sslmode, sslrootcert?, connect_timeout, application_name, row_factory)
  +-> SET TRANSACTION READ ONLY when requested
  +-> SELECT set_config('statement_timeout', <ms>, true)
  |
  v
DatabaseSessionPort
  +-> fetch_all(sql, params, max_rows?) -> QueryResult(columns, rows, truncated)
  +-> execute(sql, params) -> rowcount
  +-> execute_many(sql, rows) -> rowcount
  |
  v
success -> commit; any exception -> rollback
psycopg.Error -> IngestionError (read-only) or LoadError (writable)
                 context: error_type, optional sqlstate; never DSN/SQL/values
```

`PostgresDatabase` is constructed in `main.py` only when `AGENT_ETL_DATABASE_URL` is set. The
adapter does not connect at startup, so the API remains available without PostgreSQL. SQL
text and identifiers remain the caller's responsibility; ingestion and loading modules must
allowlist/quote identifiers and pass all values as parameters.

## 10. Interfaces (`src/interfaces/api/`)

| Component | Purpose |
|---|---|
| `app.py` | Creates the FastAPI app, installs error handlers, request-size/optional API-key middleware, health router, and run router. |
| `routes/health.py` | Returns service metadata. Health is currently a constant `ok`; dependency probes can be added later. |
| `routes/runs.py` | `POST /runs`, `GET /runs/{id}`, approve, cancel, and logs endpoints. |
| `schemas/runs.py` | Strict request schemas plus run/plan/result/cleanup/log/error response schemas. |
| `schemas/health.py` | Strict health response schema. |
| `errors.py` | Maps `EtlError`, request-validation failures, HTTP errors, and unexpected exceptions to `{code, message, retryable, details?}`. |

API behavior:

- `POST /runs` accepts a message and/or a JSON plan. The plan is parsed and validated before
  a run is created; message-only requests return `awaiting_clarification` until a plan builder
  is configured.
- Ready runs are submitted to `BackgroundSchedulerPort`; approval-gated runs are submitted
  after a successful approval.
- `RunManager` keeps per-run workflows (which own their cancellation tokens), outcomes, and
  logs in process memory. `RunCheckpointPort` stores run snapshots, not execution results.
- Responses expose result status, output count, data availability, and sanitized step errors;
  raw DataFrames are not serialized.
- `AGENT_ETL_API_KEY` optionally protects `/runs`; `/health` stays public.
- `AGENT_ETL_MAX_REQUEST_BYTES` rejects oversized `Content-Length` requests. Rate limiting is
  a deployment-level control.

## 11. End-to-end flows

### Execute a validated plan directly

```text
caller
  -> ExecutePlanUseCase.execute(plan)
       -> PlanValidator.validate(plan)
       -> RegistryStepRunner.run_source(...)
            -> ModuleRegistry.function_for(...)
            -> SandboxExecutor.run(...)
       -> RegistryStepRunner.run_transformation(...) for each step
       -> RegistryStepRunner.run_destination(...)
       -> PlanExecutionResult
```

### Run the bounded workflow

```text
caller
  -> RunWorkflow.start(request)
       -> RunIntakeCoordinator.prepare(...)
            -> PlanIntakePort
            -> PlanValidator
            -> PlanHasher
            -> OperationCatalog + OperationSafetyPolicy
            -> RunStore
       -> RunWorkflow.approve(...) or RunWorkflow.run()
            -> RunApprovalCoordinator
            -> RunExecutionCoordinator
                 -> ExecutePlanUseCase
                 -> RunTerminator on failure
```

### Run through the HTTP API

```text
POST /runs
  -> middleware: API key (optional), Content-Length limit
  -> RunCreateRequest validation
  -> RunManager.create(RunCreateCommand)
       -> PydanticPlanParser.parse(payload)
       -> PlanValidator.validate(plan)
       -> resolve run_id/mode
       -> SubmittedPlanIntakeFactory.create(plan)
       -> RunWorkflowFactory.create(intake, cancellation token)
       -> RunWorkflow.start(request)
       -> RunManager stores workflow + RunOutcome
       -> ready? BackgroundSchedulerPort.submit(run_id, RunManager._run)
  -> RunResponse.from_outcome(outcome)

GET /runs/{id}
  -> RunManager.outcome(run_id)
       -> live RunWorkflow.get() or stored RunOutcome
  -> RunResponse.from_outcome(...)

POST /runs/{id}/approve
  -> RunManager.approve(run_id, approved)
       -> RunWorkflow.approve(...)
       -> ready? schedule background execution
  -> RunResponse.from_outcome(...)

POST /runs/{id}/cancel
  -> RunManager.cancel(run_id)
       -> RunWorkflow.cancel() (cancellation token + terminal state)
  -> RunResponse.from_outcome(...)

GET /runs/{id}/logs
  -> RunManager.logs(run_id)
       -> RunLogPort.entries(run_id)
  -> RunLogsResponse
```

## 12. Extension points

- **Add a transformation:** implement a deterministic pandas function, add a `ModuleSpec` in
  `application/registry/specs.py`, and bind it in `infrastructure/registry/bindings.py`.
- **Add a validation rule:** implement `PlanValidationCheck`, add it to
  `build_default_checks`, and add tests for its stable error code.
- **Replace persistence:** implement `RunCheckpointPort` (for example PostgreSQL) and wire it
  in `main.py`; no workflow code changes are required.
- **Add or replace a database adapter:** implement `DatabasePort`/`DatabaseSessionPort` (for
  example MySQL or Oracle) and wire it in `main.py`; ingestion and loading callers stay on the
  port. PostgreSQL configuration lives in `infrastructure/database/config.py`.
- **Replace plan intake:** implement `PlanIntakePort` and `PlanIntakeFactoryPort`, then wire
  the factory into `RunManager`.
- **Replace plan parsing:** implement `PlanParserPort` (for example a different schema
  version) and wire it into `RunManager`.
- **Change sandbox mechanics:** implement `SandboxRunnerPort` or replace `SandboxExecutor`;
  application and workflow code remain unchanged.
- **Change background execution:** implement `BackgroundSchedulerPort` and wire it into
  `RunManager` in `main.py`.
- **Add persistent logs:** implement `RunLogPort` (for example JSONL or PostgreSQL) and wire
  it into `RunManager`.
- **Add an API route:** depend on application ports/use cases, not infrastructure classes.
  Construct per-run workflow instances in the route or a dedicated factory.

## 13. Conventions

- Policy belongs inward; mechanisms belong in `infrastructure/`.
- Domain entities enforce their own invariants and are immutable where practical.
- Ports are small and consumer-specific (`ModuleRegistryReadPort` vs
  `ModuleFunctionResolverPort`).
- Use structured `EtlError` subclasses with stable codes and sanitized context.
- Keep composition in `main.py`; do not construct outer-layer components inside
  `infrastructure/`.
- Run one `RunWorkflow` per run; do not reuse an instance for a second `run_id`.
