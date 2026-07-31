# Implementation Roadmap & Task Breakdown
# Agent Evaluation & Regression Testing Framework ("AgentEval")

This is the companion execution plan to the SRS. Tasks are sequenced so that **the dual-mode architecture (§5.6 of the SRS) is established before the server exists** — this is the single biggest source of "major refactor" risk in this project, and building bottom-up (core engine → local mode → server → async orchestration → frontend → hardening) eliminates it by construction.

**How to use this:** work through tasks in order within a phase; phases can overlap slightly (e.g., start Phase 5 frontend scaffolding while finishing Phase 3) but do not start Phase 3 before Phase 2 is done, and do not start Phase 2 before Phase 1 is done — each phase's data model depends on the previous one's contracts being stable.

Legend: 🟢 Beginner-friendly · 🟡 Intermediate · 🔴 Advanced

---

## Phase 0 — Foundations (Week 1)

### Task 0.1 — Repository Scaffolding & Tooling 🟢
**Depends on:** nothing
**Est. time:** 3–4 hours

**Implement:**
- Monorepo structure per SRS §16 (empty folders with `__init__.py`/placeholder files).
- `backend/pyproject.toml` with Poetry or uv, Python 3.11, ruff + black (or ruff format) + mypy configured.
- Pre-commit hooks: ruff, mypy, trailing-whitespace.
- `frontend/` scaffolded with Vite + React + TypeScript template.
- GitHub Actions skeleton: `.github/workflows/ci.yml` running lint + a placeholder test on every push.
- `README.md` with project description, architecture diagram (embed the Mermaid from the SRS), and a "Quickstart" section stub you'll fill in later.
- `LICENSE` (MIT/Apache-2.0), `CONTRIBUTING.md`.

**Acceptance criteria:**
- `git clone` → `pip install -e backend` → `pytest` (even with zero tests) runs green in CI.
- `ruff check` and `mypy` pass on an empty/near-empty codebase.

**Common mistakes to avoid:**
- Skipping CI setup until "later" — you want lint/type-check gating every commit from day one, or debt accumulates invisibly.
- Choosing a package structure that mixes `agenteval_core` and `agenteval_api` code in the same importable namespace — keep them as **separate installable packages** from the start (even in the monorepo) so the dual-mode boundary is enforced by the import system itself, not just convention.

**Best practices:**
- Set up `mypy --strict` on `agenteval_core` specifically (the most reusable, highest-leverage code) even if you relax strictness elsewhere initially.

---

### Task 0.2 — Core Domain Models 🟢
**Depends on:** 0.1
**Est. time:** 4–6 hours

**Implement (in `agenteval_core/models.py`):**
- Pydantic v2 models: `ScoreResult`, `TestCase`, `Dataset`, `EvalResult`, `EvalRunSummary`, `SpanType` (enum), `Span`, `Trace`.
- Keep these **pure data models** — no DB, no HTTP, no I/O. This file should be importable with zero extra dependencies beyond `pydantic`.

**Acceptance criteria:**
- 100% of models have at least one round-trip test (`model.model_dump()` → `Model(**data)` → equality).
- No import in this module reaches outside `pydantic`/stdlib.

**Common mistakes to avoid:**
- Adding a `created_at` auto-timestamp default using `datetime.now()` at class-definition time (a classic Python footgun — it freezes to import time, not instantiation time). Use a `default_factory=datetime.utcnow`.
- Conflating the **domain model** (`agenteval_core.models.Trace`) with the **ORM model** (`agenteval_api.models.Trace` in Phase 2) — they will look similar but serve different purposes (one is the engine's contract, one is the storage schema). Keeping them as separate classes now, with a thin mapper later, avoids a painful untangling.

---

### Task 0.3 — Built-in Deterministic Scorers 🟢
**Depends on:** 0.2
**Est. time:** 4–5 hours

**Implement (in `agenteval_core/scorers/`):**
- `Scorer` Protocol (per SRS §9.1).
- `exact_match`, `contains`, `regex_match`, `json_schema_valid`, `levenshtein_similarity` scorers (pure functions/classes, no external calls).
- A `ScorerRegistry` (simple dict-based lookup by name) so scorers can be referenced by string name from config later.

**Acceptance criteria:**
- Each scorer has ≥5 unit tests covering: exact pass, exact fail, edge case (empty string, None, malformed JSON for the schema scorer), and a "does not raise on garbage input" test (scorers must return an error `ScoreResult`, never throw, since a thrown exception mid-eval-run must not crash the whole run — see Task 3.5).

**Common mistakes to avoid:**
- Letting a scorer raise an unhandled exception. **Every scorer's `score()` method must catch its own exceptions and return `ScoreResult(error=str(e))`** — decide this contract now, because the async worker in Phase 3 will assume it.

**Best practices:**
- Write scorers as small pure functions wrapped in a thin class, not big stateful objects — makes unit testing trivial and keeps them easy to sandbox later (Phase 6) since pure functions have no hidden state to isolate.

---

## Phase 1 — Local-Only Evaluation Engine (Week 2–3)

*Goal of this phase: prove the entire evaluation loop works end-to-end with zero server, zero network — this is what makes the architecture "dual-mode" from day one instead of retrofitted later.*

### Task 1.1 — EvalResultRepository Protocol + In-Memory Implementation 🟢
**Depends on:** 0.3
**Est. time:** 3 hours

**Implement:**
- `EvalResultRepository` Protocol (per SRS §9.1): `save_result`, `get_run_results`, plus `create_run`, `update_run_status`, `get_aggregate`.
- `InMemoryEvalResultRepository` — a dict-backed implementation, used purely for unit testing the engine without any I/O.

**Acceptance criteria:**
- `EvalEngine` (built next) can be fully unit-tested against `InMemoryEvalResultRepository` with no filesystem/network/DB.

**Common mistakes to avoid:**
- Defining the repository interface with *implementation-specific* method signatures (e.g., a method that returns a SQLAlchemy object) — keep every method signature in terms of `agenteval_core` domain models only. This is the contract that makes the Postgres and SQLite implementations swappable later.

---

### Task 1.2 — EvalEngine Orchestration Logic 🟡
**Depends on:** 1.1
**Est. time:** 6–8 hours

**Implement:**
- `EvalEngine.run(dataset, suite, runner) -> EvalRunSummary`:
  1. For each `TestCase` in `dataset`: call `runner(test_case.input)` to get `actual_output`.
  2. For each `Scorer` in `suite`: call `scorer.score(input, actual_output, expected_output, metadata)`.
  3. Persist each `EvalResult` via the repository.
  4. After all test cases: compute aggregates (mean/median per scorer, pass rate) and persist as `EvalRunSummary`.
- Support both a **synchronous runner** (`Callable[[Any], Any]`) and, from the start, design the method signature to allow an **async runner** later (accept `Callable[[Any], Any] | Callable[[Any], Awaitable[Any]]`, and internally detect which via `inspect.iscoroutinefunction`) — this avoids a breaking API change when you parallelize in Phase 3.

**Acceptance criteria:**
- Unit test: engine run against a 3-test-case in-memory dataset with 2 built-in scorers produces correct per-result scores and correct aggregate mean.
- Unit test: a runner that raises on one test case does not crash the whole run — that result is marked `status: "error"` and the run completes with the rest.

**Common mistakes to avoid:**
- Making the engine call scorers **serially with no error isolation** — one failing test case must not abort the batch (directly relevant to NFR-AVAIL-3, "resumability," which starts here architecturally even before workers exist).
- Hardcoding "run everything synchronously in a for-loop forever" — it's fine for v1 to *execute* synchronously in this phase, but the **interfaces** must not assume synchronicity, or Phase 3's parallelization becomes a rewrite instead of an extension.

**Best practices:**
- Write the engine so scorer execution and result persistence are cleanly separable steps — this is what lets Phase 3 swap "loop and call directly" for "enqueue a job per test case" without touching the scoring logic itself.

---

### Task 1.3 — SQLite-Backed Local Repository + Local Client 🟡
**Depends on:** 1.2
**Est. time:** 5–6 hours

**Implement:**
- `SQLiteEvalResultRepository` implementing the same Protocol, using stdlib `sqlite3` (or `sqlmodel` for less boilerplate — acceptable dependency since it's optional/local-only).
- `Client(local=True)` in the SDK: wraps `EvalEngine` + `SQLiteEvalResultRepository` pointed at a local `.agenteval/local.db` file.

**Acceptance criteria:**
- A developer can `pip install agenteval`, write a 10-line script with `Client(local=True)`, run an eval, and inspect results — **with no Docker, no Postgres, no server running.** This satisfies NFR-USE-1's spirit even before the dashboard exists.

**Common mistakes to avoid:**
- Writing SQLite-specific SQL that doesn't map cleanly to Postgres later (e.g., relying on SQLite's dynamic typing). Keep schema/types deliberately boring and portable (TEXT, REAL, INTEGER, ISO8601 strings for timestamps) since the Postgres implementation in Phase 2 should mirror this schema closely.

---

### Task 1.4 — Dataset Loading (JSONL/CSV) 🟢
**Depends on:** 1.1
**Est. time:** 2–3 hours

**Implement:**
- `Dataset.from_jsonl(path)` and `Dataset.from_csv(path)` loaders in `agenteval_core`.

**Acceptance criteria:**
- Round-trip test: write a JSONL fixture, load it, confirm `TestCase` objects match expected fields; malformed rows produce a clear `ValueError` with the line number, not a silent skip.

---

### Task 1.5 — CLI Skeleton (Local Mode) 🟡
**Depends on:** 1.3, 1.4
**Est. time:** 4–5 hours

**Implement:**
- `agenteval_cli` package using `typer` or `click`.
- `agenteval run --dataset path/to/data.jsonl --runner "python my_agent.py" --local` — runs the full loop locally, prints a results table to stdout (use `rich` for formatting).

**Acceptance criteria:**
- Running the CLI against a toy dataset + a trivial echo "agent" script produces a correct, readable results table with pass/fail counts.

**Common mistakes to avoid:**
- Building the CLI's output formatting logic *inside* the same function that computes results — separate "compute results" from "render results" now, since Phase 4 needs the same computation to also emit JSON (for CI) and a PR comment (for GitHub), not just a terminal table.

**Milestone check (end of Phase 1):** you should be able to demo "install my package, run an eval fully offline, see results" — this alone is already a legitimate, demoable artifact and a good checkpoint to commit/tag as `v0.1.0-local`.

---

## Phase 2 — Backend API & Persistence (Week 4–5)

### Task 2.1 — Postgres Schema & Alembic Migrations 🟡
**Depends on:** Phase 1 complete
**Est. time:** 6–8 hours

**Implement:**
- SQLAlchemy 2.0 async ORM models mirroring SRS §6 ER diagram (start with: `Organization`, `User`, `Project`, `ApiKey`, `Dataset`, `DatasetVersion`, `TestCase`; leave `Trace`/`Span`/`EvalRun`/`Score` for their respective tasks below to keep each migration reviewable).
- Alembic initialized, first migration generated and applied against a local Postgres (via Docker Compose).

**Acceptance criteria:**
- `alembic upgrade head` on a fresh DB succeeds; `alembic downgrade base` also succeeds cleanly (tests migration reversibility).
- A seed script creates one org/project/API key for local dev.

**Common mistakes to avoid:**
- Writing ORM models with unbounded string columns everywhere (`String` with no length, or reaching for `Text` by default) — decide column types deliberately now since retrofitting constraints onto a live table is painful.
- Forgetting `project_id` as a required, indexed foreign key on every tenant-scoped table from the very first migration — this is the foundation of the AuthZ enforcement pattern in SRS §12.2; adding it later means backfilling and touching every query.

---

### Task 2.2 — FastAPI App Skeleton, Auth 🟡
**Depends on:** 2.1
**Est. time:** 8–10 hours

**Implement:**
- `agenteval_api/main.py` app factory, dependency-injection setup (DB session, current-user/current-project dependencies).
- API key auth: hash-and-compare middleware/dependency (`Authorization: Bearer ae_live_...`), resolves to a `project_id` + role.
- JWT session auth for dashboard login (email/password with Argon2id hashing) — implement this task, OAuth (GitHub) can be deferred.
- Global exception handler emitting RFC 7807 Problem Details (SRS §7.1).
- Rate limiting middleware (e.g., `slowapi` backed by Redis) applied globally, tunable per-route later.

**Acceptance criteria:**
- `POST /v1/auth/login` with valid credentials returns a session cookie; invalid credentials return 401 with a Problem Details body, and the attempt is written to an audit log table.
- A protected route rejects requests without a valid API key/session with 401, and rejects a request for `project_id=B` using a key scoped to `project_id=A` with 403 (write this exact cross-tenant test now — it is your regression test for the most important security property in the whole system).

**Common mistakes to avoid:**
- Implementing auth checks inside individual route handlers (easy to forget in a new route later). Use a FastAPI dependency (`Depends(get_current_project)`) injected at the router level so it's structurally impossible to add a new endpoint without it.
- Storing API keys reversibly "just for now, I'll hash it later" — hash from the very first commit; retrofitting hashing means every existing key must be revoked/reissued.

---

### Task 2.3 — Trace Ingestion Endpoints + SDK Network Mode 🟡
**Depends on:** 2.2
**Est. time:** 8–10 hours

**Implement:**
- `Trace`/`Span` ORM models + migration.
- `POST /v1/traces`, `POST /v1/traces/batch`, `GET /v1/traces`, `GET /v1/traces/{id}` (SRS §7.2).
- Large-payload offload: if `len(json.dumps(payload)) > 256_000`, upload to MinIO/S3 and store a reference (SRS §6.3) — implement this from the start, not as a later optimization, since retrofitting it means migrating already-stored inline blobs.
- Extend the SDK's `Client` (from Phase 1) with a **network mode**: same `@trace`/`span()` API, but flushes to `POST /v1/traces` via a background thread with a bounded queue + exponential backoff retry + local disk fallback queue (NFR-AVAIL-2) instead of writing to SQLite.

**Acceptance criteria:**
- Integration test (testcontainers Postgres + MinIO): ingest a trace with a 500KB span payload, confirm it's stored in object storage and the DB row holds only the reference.
- SDK test: kill the mock API server mid-flush, confirm the SDK doesn't raise into the calling agent code and later successfully flushes on retry once the server is back.

**Common mistakes to avoid:**
- Making trace ingestion synchronous/blocking from the SDK's perspective — re-read NFR-AVAIL-2 before writing this; the calling agent's request latency must never depend on AgentEval's availability.
- Building span-tree reconstruction (parent/child ordering) as a runtime N+1 query pattern (`GET /v1/traces/{id}` fetching each span's children one by one) — fetch all spans for a trace in one query and assemble the tree in application code.

---

### Task 2.4 — Dataset & Test Case Endpoints with Versioning 🟡
**Depends on:** 2.1
**Est. time:** 5–6 hours

**Implement:**
- `POST /v1/datasets`, `POST /v1/datasets/{id}/versions` (copy-on-write: cloning the previous version's test cases before applying edits, per FR-DS-3), `POST .../test-cases` (single + bulk CSV/JSONL import reusing the Phase 1 loader logic — **do not duplicate parsing logic**, import `agenteval_core`'s loader here).

**Acceptance criteria:**
- Editing a test case in version 2 does not alter version 1's records (verify by asserting `dataset_version_id` on rows is immutable once created).
- Bulk import of a 10,000-row JSONL completes without timing out the HTTP request (stream/batch-insert, don't build one giant Python list then insert row-by-row).

**Common mistakes to avoid:**
- Treating "dataset versioning" as a soft `updated_at` timestamp instead of true immutable versions — this breaks FR-DS-3's reproducibility guarantee, which every downstream Eval Run relies on.

---

### Task 2.5 — Scorer Registry Endpoints 🟡
**Depends on:** 2.2
**Est. time:** 4–5 hours

**Implement:**
- `Scorer`/`ScorerVersion` ORM models + migration.
- `POST /v1/scorers` (register built-in config, LLM-judge rubric, or custom-code reference — custom code is stored as a reference/blob now, sandboxed *execution* comes in Phase 6).
- `POST /v1/eval-suites` bundling scorer versions with weights/`is_critical` flags.

**Acceptance criteria:**
- Changing a scorer's rubric text creates a new `ScorerVersion` (never mutates an existing one referenced by a past Eval Result) — write a test asserting old `EvalResult` rows still resolve to the original rubric text they were scored against.

**Milestone check (end of Phase 2):** you can ingest real traces from a real (even trivial) agent over the network, manage datasets via API, and register scorers — but eval runs don't execute yet. Good checkpoint to demo the API via the auto-generated `/docs` Swagger UI.

---

## Phase 3 — Async Evaluation Orchestration (Week 6–7)

### Task 3.1 — Redis + Celery/RQ Setup, Job Enqueueing 🟡
**Depends on:** Phase 2 complete
**Est. time:** 5–6 hours

**Implement:**
- Celery (or RQ — RQ is simpler and fine for v1; note this choice in an ADR since it's a real tradeoff) app configured against Redis.
- `EvalRun`/`EvalResult`/`Score` ORM models + migration.
- `POST /v1/eval-runs`: creates the `EvalRun` row (`status: pending`), enqueues **one job per test case** (not one giant job for the whole run — this is what makes partial failure/resumability tractable per NFR-AVAIL-3).

**Acceptance criteria:**
- Triggering an eval run against a 5-test-case dataset creates exactly 5 queued jobs, visible via `celery inspect` / RQ dashboard.

**Common mistakes to avoid:**
- Enqueueing one job for the entire run (simpler to write, but then a single crash loses all progress and you can't parallelize across workers — this directly violates NFR-SCALE-1 and NFR-AVAIL-3, both of which are load-bearing requirements, not nice-to-haves).

---

### Task 3.2 — Eval Worker: Postgres-Backed EvalEngine Execution 🟡
**Depends on:** 3.1
**Est. time:** 6–8 hours

**Implement:**
- `PostgresEvalResultRepository` implementing the same `EvalResultRepository` Protocol from Phase 1 — **this is the payoff of the dual-mode architecture: you are not writing new orchestration logic, you are plugging a new repository into the existing `EvalEngine`.**
- Worker task: given `(run_id, test_case_id)`, invoke the agent-under-test (via the configured runner callback/webhook), run all scorers in the suite, persist via the repository.
- Runner invocation strategy: for a CLI-triggered run, the "runner" is a local subprocess call the CLI made available; for a pure-API-triggered run (no CLI in the loop), the caller must supply pre-computed `actual_output` values at trigger time (document this distinction clearly — it resolves an ambiguity in FR-EVAL-1).

**Acceptance criteria:**
- Integration test: trigger a real eval run over the API against a testcontainers Postgres + Redis, confirm all `EvalResult`/`Score` rows land correctly and the run transitions `pending → running → completed`.
- Kill a worker process mid-run (simulate crash), confirm the run doesn't silently hang forever — a stale `running` job past a timeout is requeued (a "reaper" mechanism).

**Common mistakes to avoid:**
- Re-implementing scoring logic in the Celery task function instead of calling into `agenteval_core.EvalEngine` — if you find yourself writing scorer-calling code here, stop and go back to reuse the engine; this is the exact mistake the dual-mode architecture in §5.6 was designed to prevent.

---

### Task 3.3 — LLM-as-Judge Scorer with Structured Output + Caching 🟡🔴
**Depends on:** 3.2
**Est. time:** 8–10 hours

**Implement:**
- `LLMJudgeScorer` in `agenteval_core/scorers/llm_judge.py`: renders the rubric template, calls a pluggable `JudgeModelAdapter` (interface with OpenAI/Anthropic/Ollama implementations), enforces structured output via tool-calling/JSON mode (never regex-parse free text, per SRS §9.3).
- Response cache: `(scorer_version_id, sha256(input+output))` → cached `ScoreResult`, backed by Redis (or a Postgres table if you want to avoid a second cache dependency — either is fine, document the choice).
- Retry/backoff on rate-limit errors from the judge provider (respect `Retry-After` headers where provided).

**Acceptance criteria:**
- Unit tests mock the judge adapter (per SRS §13's testing best practice) and verify: correct prompt rendering, correct parsing of structured output, correct fallback to `ScoreResult(error=...)` on malformed/unparseable judge output (never crash the worker).
- A small `@pytest.mark.live_llm` test (run manually) hits a real provider once to confirm the adapter's request/response shape is correct end-to-end.
- Cache hit avoids a second API call — verify via a mock call-count assertion.

**Common mistakes to avoid:**
- Trusting the judge LLM's output format without validation — always validate against a Pydantic schema and treat a schema-validation failure as a scorer error, not a crash.
- Using the *same model* as both the agent-under-test and the judge without at least documenting the self-evaluation bias risk (SRS §9.3) — this is a real methodological detail that impresses reviewers who know the space.

---

### Task 3.4 — Aggregation, Baseline Diff, Statistical Significance 🔴
**Depends on:** 3.2
**Est. time:** 8–10 hours

**Implement:**
- Aggregate computation job (runs after the last per-test-case job in a run completes — use a Celery `chord`/RQ dependency, or a simple "last job checks if count == total, then triggers aggregation" pattern).
- `GET /v1/eval-runs/{id}/diff?baseline={id}`: joins two runs' results by `test_case_id`, computes per-scorer deltas.
- Bootstrap significance test (SRS §9.4): resample test-case-level score deltas with replacement (~1000 iterations), compute the 95% CI of the mean delta, flag `significant: true` only if the CI excludes zero.

**Acceptance criteria:**
- Unit test with a synthetic dataset where you *know* the ground truth (e.g., construct scores where the true delta is clearly noise vs. clearly a real regression) and assert the significance test correctly classifies both cases.
- `POST /v1/eval-runs/{id}/set-baseline` correctly scopes "the baseline" per `(dataset_id, eval_suite_id)` pair, not globally per project (a project may have many dataset/suite combinations, each with its own baseline).

**Common mistakes to avoid:**
- Reporting a regression on any negative delta, however small — this is the "toy" version of this feature; the significance-tested version is what separates this project from a basic CRUD app and is worth the extra implementation time.
- Computing aggregates by re-scanning all `EvalResult` rows on every dashboard page load instead of persisting the computed `aggregate_metrics` JSONB on the `EvalRun` row once, at completion time (cheap to compute once, expensive to recompute per request).

---

### Task 3.5 — Idempotency & Resumability 🔴
**Depends on:** 3.1–3.4
**Est. time:** 4–5 hours

**Implement:**
- `POST /v1/eval-runs/{id}/retry`: re-enqueues only the `EvalResult` rows with `status: "error"` or missing entirely (not the whole run).
- Idempotency key on trace ingestion (client-supplied `trace_id`, upsert semantics — re-sending the same trace_id updates rather than duplicates, per FR-TRACE-3).

**Acceptance criteria:**
- Simulate 30% of jobs in a run failing (inject a fault), confirm the run is marked `partial`, and confirm `retry` only re-processes the failed subset (verify via job-count assertions, not just final state).

**Milestone check (end of Phase 3):** the full server-side evaluation loop works: trigger a run, workers score it in parallel, aggregates + diff compute correctly, partial failures recover gracefully. This is the technical core of the project — tag as `v0.5.0`.

---

## Phase 4 — CI/CD Gating (Week 8)

### Task 4.1 — CLI Gate Command Against Remote API 🟡
**Depends on:** Phase 3 complete
**Est. time:** 5–6 hours

**Implement:**
- `agenteval run --config agenteval.yaml --gate` (non-local mode): triggers a remote eval run via the API, polls `GET /v1/eval-runs/{id}` until `completed`/`failed`/`partial`, fetches the diff.
- Reuse the Phase 1.5 "compute vs. render" separation: the gate policy evaluation function takes a diff payload and config, returns a `GateDecision(passed: bool, reasons: list[str])` — independent of how that decision is displayed.

**Acceptance criteria:**
- Against a live local stack (docker compose up), running the CLI with a deliberately-failing threshold produces exit code `1` and a clear stdout explanation; a passing run produces exit code `0`.
- A network failure to reach the API produces exit code `2`, distinctly (SRS §10.3) — write a specific test for this using a mock server that returns connection errors.

**Common mistakes to avoid:**
- Polling with a fixed short interval and no timeout — long-running eval suites (many LLM-judge calls) need a generous, configurable timeout with exponential backoff polling, or CI jobs will falsely time out.

---

### Task 4.2 — `agenteval.yaml` Config Parsing + Policy Evaluation 🟡
**Depends on:** 4.1
**Est. time:** 3–4 hours

**Implement:**
- Pydantic schema for `agenteval.yaml` (SRS §10.1), with clear validation error messages (NFR-USE-2) if a user misconfigures it (e.g., references a scorer name that doesn't exist in the suite).
- `GateDecision` evaluation logic: min mean score per scorer, max regression delta (using the significance-tested diff from 3.4, not raw delta), critical tags, latency/cost budgets.

**Acceptance criteria:**
- A malformed YAML (missing required field) fails fast with a specific, actionable error before any API calls are made — don't let a config typo burn CI minutes triggering a real eval run that then fails to gate correctly.

---

### Task 4.3 — GitHub Action + PR Comment Bot 🟡
**Depends on:** 4.1, 4.2
**Est. time:** 5–6 hours

**Implement:**
- Composite GitHub Action (`.github/actions/agenteval-gate/action.yml`) wrapping CLI install + run (SRS §10.2).
- PR comment bot: formats the diff into a Markdown table (regressed cases in a collapsible `<details>` block to avoid huge PR comments), posts/updates a single comment (find-and-update by a hidden HTML marker comment, don't spam a new comment on every push).

**Acceptance criteria:**
- Full dry run against a real (throwaway) public GitHub repo: open a PR that intentionally regresses a scorer, confirm the Action fails the check and posts a correctly formatted comment; open a PR that passes, confirm a green check and a "no regressions" comment.

**Common mistakes to avoid:**
- Requiring secrets that aren't clearly documented (judge LLM API key, AgentEval API key) — a broken quickstart here is the single most damaging thing for an open-source project's adoption/first impression; test this Action from a completely fresh repo, not just your dev environment.

**Milestone check (end of Phase 4):** you have a genuinely demoable, screen-recordable moment — "open a PR, watch the bot comment with a real regression table, merge is blocked." This is the best 60-second demo clip for your README/LinkedIn post. Tag `v0.6.0`.

---

## Phase 5 — Frontend Dashboard (Week 9–10)

### Task 5.1 — Frontend Scaffolding, Generated API Client, Auth Flow 🟡
**Depends on:** Phase 2 complete (can start in parallel with Phase 3/4)
**Est. time:** 6–8 hours

**Implement:**
- Vite + React + TS + Tailwind + shadcn/ui installed and configured.
- `openapi-typescript` codegen script (`npm run generate-api`) pointed at the backend's `/openapi.json`, run in CI to fail the build if types drift from the backend (SRS §5.4's "never hand-write API types" rule enforced mechanically, not just as a guideline).
- Login page + protected route wrapper using the JWT cookie session from Task 2.2.

**Acceptance criteria:**
- Changing a backend Pydantic response schema and re-running codegen produces a visibly different generated type, and a frontend file using the old shape fails `tsc` — proving the drift-detection actually works, not just exists in theory.

---

### Task 5.2 — Trace Explorer 🟡
**Depends on:** 5.1, Task 2.3
**Est. time:** 8–10 hours

**Implement:**
- Trace list (TanStack Table, cursor-paginated, filterable by environment/tag/date range).
- Trace detail view: span waterfall/timeline (custom SVG or a small library — building the waterfall yourself is a nice, contained frontend-engineering flex for the portfolio), expandable spans showing input/output/tokens/cost, color-coded by `span_type`/`status`.

**Acceptance criteria:**
- With a seeded dataset of ~500 traces with varying span counts, list view loads within the NFR-PERF-2 budget and the waterfall correctly nests parent/child spans (including a trace with 4+ levels of nesting).

**Common mistakes to avoid:**
- Fetching the full span tree for every row in the list view "just in case" — the list view should only fetch summary fields (name, duration, status, cost); the full tree is fetched lazily only when a trace is opened.

---

### Task 5.3 — Dataset Manager UI 🟡
**Depends on:** 5.1, Task 2.4
**Est. time:** 6–7 hours

**Implement:**
- Dataset list, version history timeline, test-case table (CRUD + bulk CSV/JSONL upload with client-side preview before submit), tag filter chips.

**Acceptance criteria:**
- Uploading a malformed CSV shows row-level validation errors before submission (reusing/mirroring the backend's validation messages, not a generic "upload failed").

---

### Task 5.4 — Eval Run Results Table + Baseline Diff View 🟡🔴
**Depends on:** 5.1, Task 3.4
**Est. time:** 8–10 hours

**Implement:**
- Results table: one row per test case, one column per scorer, sortable/filterable by pass/fail/tag.
- Diff view: toggle to overlay baseline scores, regressed cases highlighted red with the significance indicator surfaced explicitly (e.g., "↓0.06 (not statistically significant)" vs. "↓0.09 (significant)") — this is the UI payoff of Task 3.4's statistical rigor; don't let it get lost as just a number.
- Aggregate score cards + cost/latency summary at the top of the run view.

**Acceptance criteria:**
- Given a seeded run + baseline with known regressed/improved/unchanged cases, the diff view correctly categorizes and colors each row, and the significance label matches the backend's computed value exactly (no re-deriving it client-side with different logic — always trust the server's computation).

---

### Task 5.5 — Trend Dashboard Charts 🟡
**Depends on:** 5.1, Task 3.4
**Est. time:** 5–6 hours

**Implement:**
- `GET /v1/metrics/trends` endpoint (add to backend if not already built in Phase 3) + Recharts line charts: score-over-time per scorer, cost-over-time, latency p50/p95 over time, with date-range selection and environment filter.

**Acceptance criteria:**
- Charts correctly handle sparse data (a project with only 2 eval runs should render a sensible 2-point line, not crash or show a broken axis).

---

### Task 5.6 — Scorer Builder UI 🟡
**Depends on:** 5.1, Task 2.5
**Est. time:** 6–7 hours

**Implement:**
- Form-based scorer creation (built-in config fields vary by scorer type; a rich text/code editor for the LLM-judge rubric template with `{input}/{output}/{expected}` placeholder highlighting).
- "Test on one example" preview: pick or paste a sample input/output, run just that one scorer synchronously, show the result inline (calls a lightweight `POST /v1/scorers/{id}/preview` endpoint you'll need to add to the backend — a small, worthwhile Phase 2/3 addition).

**Acceptance criteria:**
- Creating a new `ScorerVersion` via this UI and immediately previewing it reflects the exact same scoring logic used in a real eval run (no UI-side reimplementation of scoring — the preview endpoint must call the same `agenteval_core` scorer code).

**Milestone check (end of Phase 5):** the full product is usable end-to-end through the UI, no API client (Postman/curl) needed for a first-time user. Record your demo video now while it's freshest. Tag `v0.8.0`.

---

## Phase 6 — Security Hardening (Week 11, part 1)

### Task 6.1 — Sandboxed Custom Scorer Execution 🔴
**Depends on:** Task 2.5 (custom scorer registration)
**Est. time:** 10–12 hours

**Implement:**
- A minimal container-per-execution sandbox: worker spawns a short-lived Docker container (or gVisor `runsc` runtime if you want the deeper isolation story for your README) from a locked-down base image, with `--network none`, `--read-only`, `--memory`, `--cpus`, and a wall-clock timeout via `docker run --rm` + a supervising `timeout` wrapper.
- Communication: pass `{input, output, expected, metadata}` via stdin as JSON, scorer code writes `{score, rationale}` as JSON to stdout; worker parses and validates against the `ScoreResult` schema.
- Explicit test suite of deliberately malicious scorers: infinite loop (must be killed by timeout), attempted network call (must fail/hang with no egress), attempted large-memory allocation (must be OOM-killed within the container, not the host), attempted filesystem write (must fail against read-only fs).

**Acceptance criteria:**
- Every "malicious scorer" test in NFR-SEC-3/SRS §13's security testing row passes: the host process/worker is never affected, only the sandboxed container is killed, and the failure surfaces as a normal `ScoreResult(error=...)`, not a worker crash.

**Common mistakes to avoid:**
- Running custom code with `exec()`/`eval()` in-process "to keep it simple for now" — this is a genuine, not theoretical, remote-code-execution vulnerability the moment this project is self-hosted by anyone else; do not ship custom scorers without the sandbox, even in an early release. If you need to ship something before the sandbox is ready, disable the custom-scorer feature behind a config flag rather than shipping it unsandboxed.

**Best practices:**
- Document the sandbox's isolation guarantees precisely in the README (what it protects against, what it doesn't, e.g. "not hardened against a determined adversary with host access, appropriate for trusted internal users") — honest security scoping is itself a signal of engineering maturity to anyone reviewing the repo.

---

### Task 6.2 — Secrets Encryption & Redaction Rules 🔴
**Depends on:** Task 2.2 (auth), Task 2.3 (ingestion)
**Est. time:** 5–6 hours

**Implement:**
- Envelope encryption for stored provider API keys (judge LLM credentials, webhook secrets): AES-256-GCM with a master key sourced from an environment variable (documented as "use a real KMS in production" — implementing a full KMS integration is out of scope but the interface should allow swapping in one).
- Configurable redaction rules applied at trace ingestion: regex patterns for common secret formats (API key prefixes, emails, credit-card-like patterns) masked before persistence, per-project configurable rule list.

**Acceptance criteria:**
- Ingest a trace containing a fake but realistic-looking API key string in a span's input; confirm the persisted row has it masked, and confirm the original raw payload sent over the wire is never written to disk anywhere (including logs).

---

### Task 6.3 — RBAC & Rate-Limit Audit 🟡
**Depends on:** all API endpoints built (Phases 2–5)
**Est. time:** 4–5 hours

**Implement:**
- A checklist-driven audit pass over every endpoint: confirm role requirements match the SRS §3.1 role matrix (`viewer` cannot mutate, `member` cannot manage billing/API keys, etc.), confirm every list/get endpoint filters by `project_id` from the auth context.
- Tighten rate limits per-endpoint (ingestion needs a high limit, auth endpoints need a low, strict limit to slow brute-force attempts).

**Acceptance criteria:**
- An automated test iterates every route and asserts a `viewer`-role token receives 403 on every mutating verb (POST/PUT/PATCH/DELETE) it shouldn't have access to — a single parametrized test covering the whole API surface, not one-off tests per route (much higher leverage, and it automatically covers new routes added later).

**Milestone check (end of Phase 6):** the project is safe to actually let a stranger self-host and point at real (non-toy) data. Tag `v0.9.0`.

---

## Phase 7 — Production Monitoring & Alerting (Week 11, part 2)

### Task 7.1 — Production Sampler (Scheduled Job) 🟡
**Depends on:** Task 3.2 (worker infra), Task 2.3 (traces tagged with environment)
**Est. time:** 5–6 hours

**Implement:**
- A periodic Celery beat task (or RQ scheduler): every N minutes, sample X% of `environment: production` traces ingested since the last run, run the project's configured "monitoring suite" of scorers against them (reusing `EvalEngine` again — no new orchestration logic).

**Acceptance criteria:**
- With a seeded stream of production traces, the sampler selects approximately the configured percentage (verify via statistical assertion over many runs, not exact count) and produces `EvalResult` rows tagged as `trigger_source: monitoring`.

---

### Task 7.2 — Alert Rules & Webhook/Slack Dispatch 🟡
**Depends on:** 7.1
**Est. time:** 5–6 hours

**Implement:**
- `AlertRule`/`AlertEvent` models + migration (SRS §6.1).
- After each monitoring batch, compute a rolling average per scorer; if it crosses a configured threshold, fire an `AlertEvent` and dispatch via the configured channel (generic webhook POST, Slack incoming webhook format, or email via SMTP).
- Deduplication: don't refire the same alert every batch while the condition persists — only on state transition (ok→breached) plus a periodic re-notify (e.g., every 6 hours) while still breached.

**Acceptance criteria:**
- Integration test: feed a sequence of monitoring batches that cross a threshold, confirm exactly one alert fires on the transition, none fire while still breached within the cooldown window, and one fires again after the cooldown if still breached.

---

### Task 7.3 — Human-in-the-Loop Review Queue 🟡 (optional/stretch)
**Depends on:** 7.1
**Est. time:** 6–8 hours

**Implement:**
- A UI queue of low-score/low-confidence production traces flagged for manual review; reviewer can annotate (correct/incorrect, add a corrected expected output) and "promote" the trace into a Dataset as a new `TestCase` — closing the loop from a real production failure into a permanent regression test.

**Acceptance criteria:**
- Promoting a reviewed trace creates a new `DatasetVersion` with the new test case, traceable back to the original production `trace_id` in its metadata.

**Milestone check (end of Phase 7):** the "closed loop" story — production issue → flagged → reviewed → becomes a permanent regression test → gates future CI — is complete and is genuinely the most impressive narrative arc to walk an interviewer through. Tag `v1.0.0-rc1`.

---

## Phase 8 — Deployment, Observability & Polish (Week 12–13)

### Task 8.1 — Docker Compose Finalization 🟢
**Depends on:** all prior phases functionally complete
**Est. time:** 3–4 hours

**Implement:**
- Finalize `ops/docker-compose.yml` (SRS §14.1) as the canonical local-dev/quickstart environment; add a `Makefile` or `just` recipes (`make up`, `make seed`, `make test`) to remove friction.

**Acceptance criteria:**
- A person with zero prior context clones the repo, runs one documented command, and sees a working dashboard with seed data within the NFR-USE-1 10-minute budget — **test this literally on a machine/VM that has never had the project on it before.**

---

### Task 8.2 — Kubernetes / Helm Chart 🔴
**Depends on:** 8.1
**Est. time:** 8–10 hours

**Implement:**
- Helm chart per SRS §14.2: separate Deployments for api/worker/frontend, HPA on worker queue depth (custom metric via KEDA or a Prometheus adapter — this is a genuinely advanced, resume-worthy detail if you implement it rather than just CPU-based autoscaling), Ingress + cert-manager config, migration pre-upgrade hook Job.

**Acceptance criteria:**
- `helm install` against a local `kind`/`minikube` cluster succeeds and produces a working stack; a migration is applied exactly once even with `--replicas=3` on the api Deployment (proving the pre-upgrade hook pattern avoids the race condition).

**Common mistakes to avoid:**
- Running `alembic upgrade head` in the application's container entrypoint/startup code — with multiple replicas starting concurrently this causes migration race conditions; this is why SRS §14.2 specifies a dedicated hook Job.

---

### Task 8.3 — Observability: Prometheus + Grafana 🟡
**Depends on:** all services running
**Est. time:** 5–6 hours

**Implement:**
- `/metrics` endpoint on the API (request latency histograms, error rate counters) via `prometheus-fastapi-instrumentator` or hand-rolled; worker exposes queue depth/throughput/job-duration metrics.
- A committed Grafana dashboard JSON (`ops/grafana/agenteval-overview.json`) covering the NFR-OBS-1 metrics.

**Acceptance criteria:**
- Import the committed dashboard JSON into a fresh Grafana instance pointed at the Compose stack's Prometheus and confirm every panel renders real data (no "No Data" panels from stale/renamed metric names).

---

### Task 8.4 — Load Testing & Performance Tuning 🔴
**Depends on:** 8.1–8.3
**Est. time:** 6–8 hours

**Implement:**
- k6 (or Locust) scripts: sustained trace-ingestion load test, eval-run-triggering burst test, dashboard query load test — each targeting the specific NFR-PERF thresholds from SRS §4.1.
- Fix whatever the load test reveals (likely candidates: missing indexes surfaced under real query patterns, connection pool sizing, N+1 queries in the trace detail endpoint).

**Acceptance criteria:**
- A committed load-test report (markdown or HTML, checked into `docs/perf/`) showing before/after numbers for at least one real bottleneck you found and fixed — this artifact alone is a strong interview talking point ("here's a real performance problem I found and how I diagnosed and fixed it"), so treat it as a deliverable, not just a debugging exercise.

---

### Task 8.5 — Documentation, Demo Agent, README, Demo Video 🟢
**Depends on:** everything
**Est. time:** 8–10 hours

**Implement:**
- `examples/example-support-agent/`: a small, realistic reference agent (a few tool calls + an LLM call) fully instrumented with the SDK, with its own dataset, eval suite, and a working `agenteval.yaml` — this is what a first-time visitor should be able to clone and run in under 10 minutes.
- README: problem statement, architecture diagram (embed SRS Mermaid diagrams), quickstart, screenshot/GIF of the dashboard, link to a 90-second demo video, results table (some real numbers — e.g., "eval throughput: N test cases/sec with 4 workers", "trace ingestion p95: Xms"), and an explicit "Architecture Decisions" section summarizing the dual-mode design (§5.6) and why it matters — this is the single highest-leverage paragraph for a technical reviewer skimming the repo.
- Optionally: a short ADR (Architecture Decision Record) log in `docs/adr/` for the 3–4 biggest decisions (dual-mode core, Celery vs RQ, sandbox approach, statistical significance for regressions) — ADRs are a well-recognized professional-engineering artifact and cost little to write once the decision's already made.

**Acceptance criteria:**
- Someone outside the project (a friend, or you after a week away) can follow the README alone, with zero additional context, to a working demo.

**Milestone check (end of Phase 8): `v1.0.0`.** At this point you have a genuinely production-grade, portfolio-defining system with a coherent architectural narrative, real metrics, and a live demo — ready to link from your CV.

---

## Summary Timeline

| Phase | Focus | Weeks | Cumulative |
|---|---|---|---|
| 0 | Foundations | 1 | 1 |
| 1 | Local evaluation engine (dual-mode core) | 2 | 3 |
| 2 | Backend API & persistence | 2 | 5 |
| 3 | Async evaluation orchestration | 2 | 7 |
| 4 | CI/CD gating | 1 | 8 |
| 5 | Frontend dashboard | 2 | 10 |
| 6 | Security hardening | 0.5 | 10.5 |
| 7 | Production monitoring & alerting | 0.5 | 11 |
| 8 | Deployment, observability, polish | 2 | 13 |

**Total: ~13 weeks at a sustained part-time pace (~15–20 hrs/week), or ~6–7 weeks full-time.** If you need to cut scope for a first working version, cut in this order: Task 7.3 (review queue) → Task 8.2 (Kubernetes/Helm, Compose is enough for a demo) → Task 6.1's gVisor hardening (basic Docker isolation is an acceptable interim) → Phase 7 entirely (monitoring/alerting) — never cut Phase 1 (the dual-mode core) or Task 2.2's AuthZ pattern; those are the two things that are genuinely expensive to retrofit.
