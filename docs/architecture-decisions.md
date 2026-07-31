# Architecture Decision Records

Short-form log of the biggest structural decisions in this codebase.

## ADR-1: Zero-framework-dependency core engine (`agenteval_core`)

**Decision:** All evaluation orchestration logic (scoring, aggregation,
statistical significance) lives in a pure Python package with no
dependency on FastAPI, SQLAlchemy, or Celery.

**Why:** The SDK/CLI must work fully offline (no server required) for a
fast local dev loop, while the server must run the exact same logic at
scale across many workers. Putting orchestration logic in FastAPI route
handlers or Celery tasks would mean writing it twice and having it
silently drift. Instead, both the `SQLiteEvalResultRepository` (SDK/CLI)
and `PostgresEvalResultRepository` (server) implement the same
`EvalResultRepository` protocol, and `EvalEngine` never knows which one
it's talking to.

**Trade-off accepted:** the repository abstraction adds a layer of
indirection that a single-mode system wouldn't need. Worth it here
because the dual-mode requirement is explicit (see `docs/SRS.md`
section 5.6), not speculative.

## ADR-2: One Celery job per test case, not one job per run

**Decision:** `dispatch_eval_run()` enqueues N jobs (one per test case)
plus a `chord` callback that finalizes the run once all N complete,
rather than a single job that loops internally.

**Why:** A single-job design is simpler to write but means a worker
crash loses all progress on a run, and runs can't be parallelized
across multiple workers. Per-test-case jobs make partial failure
recoverable (`status: partial`, retryable) and let eval throughput
scale horizontally with worker count.

**Trade-off accepted:** more Redis/Postgres traffic (many small writes
instead of one big one) and Celery `chord` semantics are less
beginner-friendly than a plain task. Worth it for the
reliability/scalability properties.

## ADR-3: Statistical significance testing on regressions, not raw deltas

**Decision:** The baseline diff (`GET /v1/eval-runs/{id}/diff`) doesn't
just report "new mean < old mean" -- it runs a paired bootstrap over
per-test-case score deltas and only flags a regression as `significant`
if the 95% confidence interval excludes zero.

**Why:** LLM-judge scores are inherently noisy (the same agent, run
twice, can produce different judge scores). Flagging every negative
delta as a regression would make the gate untrustworthy within a few
CI runs -- teams would start ignoring it. The bootstrap approach is
standard practice for exactly this kind of paired-sample noise problem.

**Trade-off accepted:** the diff endpoint is slower (1000 resampling
iterations per scorer) and harder to explain to a new contributor than
a raw delta. Worth it because it's the difference between a credible
regression-testing tool and a noisy one nobody trusts.

## ADR-4: Custom scorer code execution is sandboxed, or disabled

**Decision:** Arbitrary user-supplied Python scorer code is never
`exec()`'d in the API or worker process. It only runs inside an
isolated, network-restricted, resource-limited container. This feature
is **not included in the v0.1 release** in this repository -- see
`docs/SRS.md` section 12 and the README's "Known Limitations" section --
rather than shipping it unsandboxed.

**Why:** Running untrusted code in-process is a real, not theoretical,
remote-code-execution vector the moment this project is self-hosted by
anyone other than its original author. Shipping a half-secured version
would be worse than not shipping the feature at all.

## ADR-5: Celery/RQ chosen over one giant async task queue inside FastAPI

**Decision:** Async evaluation work runs in separate Celery worker
processes, not as FastAPI `BackgroundTasks` or an in-process asyncio
queue.

**Why:** Eval runs can involve hundreds of LLM-judge calls per run and
need to survive an API process restart/redeploy. `BackgroundTasks` dies
with the request's worker process and doesn't scale independently of
API traffic. A dedicated worker pool scales eval throughput
independently of API request throughput, which is the correct axis to
scale on for this workload.
