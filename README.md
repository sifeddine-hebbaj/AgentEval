# AgentEval

**An open-source agent evaluation and regression testing framework.** Instrument your LLM agent, capture its execution traces, score them against configurable rubrics, and gate CI/CD when quality regresses — self-hosted, framework-agnostic, and usable fully offline before you ever stand up a server.

```
Agent (any framework) → AgentEval SDK → Eval Suite (scorers) → Baseline diff → CI gate
```

This is not a demo wrapper around an LLM API. It's a real evaluation-infrastructure system: a modular-monolith FastAPI backend, Celery-based async evaluation workers, a Postgres schema with immutable dataset versioning, a statistically-rigorous regression detector (paired bootstrap significance testing, not raw score deltas), a React dashboard, a CLI with CI/CD gating, and an SDK that works with zero server at all for local development.

---

## Table of contents

- [Why this exists](#why-this-exists)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Quickstart (Docker)](#quickstart-docker)
- [Local development (without Docker)](#local-development-without-docker)
- [Environment variables](#environment-variables)
- [Database migrations](#database-migrations)
- [Running each service](#running-each-service)
- [Using the SDK](#using-the-sdk)
- [Using the CLI](#using-the-cli)
- [Using the REST API](#using-the-rest-api)
- [Using the dashboard](#using-the-dashboard)
- [Creating datasets, scorers, and eval suites](#creating-datasets-scorers-and-eval-suites)
- [Regression testing & baselines](#regression-testing--baselines)
- [CI/CD integration](#cicd-integration)
- [Example workflow, end to end](#example-workflow-end-to-end)
- [Running tests](#running-tests)
- [Troubleshooting](#troubleshooting)
- [Deployment](#deployment)
- [Known limitations & what's not included](#known-limitations--whats-not-included)
- [Project structure](#project-structure)
- [License](#license)

---

## Why this exists

Most AI portfolio projects are either a thin LLM wrapper or a toy classifier. AgentEval is the opposite kind of project: **infrastructure that makes other agents trustworthy in production.** The two hardest, highest-value parts of building an agent evaluation system are:

1. Making local evaluation and server-side evaluation share **one** evaluation engine, so you never write orchestration logic twice.
2. Not lying to yourself about regressions — LLM-judge scores are noisy, so a raw "new score < old score" check produces false positives constantly. This project runs a paired bootstrap significance test before ever calling something a regression.

Full requirements and design rationale: [`docs/SRS.md`](docs/SRS.md) (the Software Requirements Specification this was built from) and [`docs/architecture-decisions.md`](docs/architecture-decisions.md) (why the biggest structural choices were made).

## Architecture

```mermaid
flowchart LR
    SDK["Python SDK<br/>(local or network mode)"] -->|traces| API[FastAPI API]
    CLI["CLI (agenteval)"] -->|trigger + gate| API
    FE["React Dashboard"] -->|REST| API
    API --> PG[(PostgreSQL)]
    API --> S3[(MinIO / S3)]
    API --> Q[(Redis queue)]
    Q --> W["Celery Eval Workers"]
    W -->|judge calls| LLM["OpenAI / Anthropic / Ollama"]
    W --> PG
```

The **core evaluation engine** (`backend/agenteval_core`) has zero dependency on FastAPI, SQLAlchemy, or Celery. It's reused, unmodified, by:
- the **SDK/CLI's local mode** (SQLite-backed, no server needed), and
- the **Celery workers** (Postgres-backed, horizontally scalable).

This is the single most important design decision in the codebase — see [ADR-1](docs/architecture-decisions.md#adr-1-zero-framework-dependency-core-engine-agenteval_core).

**Services:** `postgres` (system of record) · `redis` (job queue + cache) · `minio` (large trace-payload storage) · `api` (FastAPI) · `worker` (Celery) · `frontend` (React, served via nginx).

## Prerequisites

- **Docker & Docker Compose** (v2+) — for the quickstart path.
- **Python 3.11+** and **Node.js 20+** — for local (non-Docker) development.
- An API key from **OpenAI**, **Anthropic**, or a local **Ollama** install — only required if you use the `llm_judge` scorer. Every deterministic scorer (`exact_match`, `contains`, `regex_match`, `json_schema_valid`, `levenshtein_similarity`, `latency_threshold`, `cost_threshold`) works with zero API keys.

## Quickstart (Docker)

```bash
git clone <this-repo-url> agenteval && cd agenteval
cp .env.example .env
# (optional) edit .env to add OPENAI_API_KEY / ANTHROPIC_API_KEY for the llm_judge scorer

docker compose up --build -d
docker compose exec api python -m agenteval_api.seed
```

The seed command prints a `project_id` and an `api_key`. Then:

- **Dashboard:** http://localhost:8080 — paste the `api_key` on the login screen.
- **API docs (Swagger UI):** http://localhost:8000/docs
- **MinIO console:** http://localhost:9001 (`minioadmin` / `minioadmin`)

Send your first trace:

```bash
export AGENTEVAL_API_KEY=<the api_key from seed output>
python examples/example-support-agent/agent.py
```

Refresh the dashboard's Traces page — you'll see the run, including its retrieval and generation spans.

## Local development (without Docker)

```bash
# 1. Postgres + Redis (only infra you need locally; MinIO is optional --
#    payloads under 256KB are stored inline and never touch object storage)
#    Use Docker for just these two, or install them natively:
docker compose up -d postgres redis

# 2. Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[api,cli,sdk,dev,judge-openai,judge-anthropic,judge-local]"
export DATABASE_URL=postgresql+asyncpg://agenteval:agenteval@localhost:5432/agenteval
export REDIS_URL=redis://localhost:6379/0
alembic upgrade head
python -m agenteval_api.seed

# 3. API (terminal 1)
uvicorn agenteval_api.main:app --reload --port 8000

# 4. Worker (terminal 2)
celery -A agenteval_worker.tasks:celery_app worker --loglevel=info

# 5. Frontend (terminal 3)
cd ../frontend
npm install
npm run dev   # http://localhost:5173, proxies /v1 to localhost:8000
```

## Environment variables

All variables live in `.env` (see `.env.example` for the full annotated list). The most important ones:

| Variable | Used by | Purpose |
|---|---|---|
| `DATABASE_URL` | api, worker, migrations | `postgresql+asyncpg://...` connection string |
| `REDIS_URL` | api, worker | Celery broker/backend and API rate-limit cache |
| `SECRET_KEY` | api | Signs dashboard JWT sessions — **change in production** |
| `JUDGE_PROVIDER` | worker | `openai` \| `anthropic` \| `ollama` |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | worker | Only needed if you use `llm_judge` scorers with that provider |
| `OLLAMA_BASE_URL` | worker | Only needed for the fully-offline judge path |
| `S3_ENDPOINT_URL` / `S3_ACCESS_KEY` / `S3_SECRET_KEY` | api | Large trace-payload storage (MinIO locally, real S3 in prod) |
| `CORS_ORIGINS` | api | JSON array of allowed dashboard origins |

## Database migrations

Schema changes are managed exclusively through Alembic — never edit tables by hand.

```bash
cd backend
alembic upgrade head                          # apply all pending migrations
alembic downgrade -1                           # roll back one migration
alembic revision --autogenerate -m "add X"     # generate a new migration after editing agenteval_api/models/orm.py
```

The initial migration (`migrations/versions/`) was generated against a real Postgres 16 instance and includes all 21 tables described in `docs/SRS.md` section 6 (organizations, projects, API keys, datasets + versions, test cases, traces, spans, scorers + versions, eval suites, eval runs, eval results, scores, baselines, alert rules, audit log). Upgrade/downgrade reversibility is verified in CI.

## Running each service

| Service | Local command | Docker Compose service |
|---|---|---|
| API | `uvicorn agenteval_api.main:app --reload --port 8000` | `api` |
| Worker | `celery -A agenteval_worker.tasks:celery_app worker --loglevel=info` | `worker` |
| Frontend | `npm run dev` (in `frontend/`) | `frontend` |
| Migrations | `alembic upgrade head` (in `backend/`) | `migrate` (runs once, exits) |

## Using the SDK

### Local mode (no server, SQLite-backed)

```python
from agenteval_sdk import Client
from agenteval_core.scorers.deterministic import ExactMatchScorer

client = Client(local=True)
dataset = client.load_dataset("my_dataset.jsonl")

def my_agent(query: str) -> str:
    return call_my_agent(query)

summary = client.run_eval(dataset, my_agent, scorers=[ExactMatchScorer()])
print(summary.aggregate_metrics)  # {'mean_scores': {...}, 'pass_rate': 0.92, ...}
```

### Network mode (instrumenting a real agent)

```python
from agenteval_sdk import Client, trace, span

client = Client(api_key="ae_live_...", base_url="http://localhost:8000", project="my-agent")

@trace(client=client, name="my_agent")
def run_agent(query: str) -> str:
    with span(type="retrieval", name="fetch_docs") as s:
        docs = retrieve(query)
        s.set_output(docs)

    with span(type="llm_call", name="generate", model="claude-sonnet-5") as s:
        response = call_llm(query, docs)
        s.set_output(response)
        s.set_usage(prompt_tokens=120, completion_tokens=48, cost=0.0009)

    return response

run_agent("How do I reset my password?")
client.flush()  # or just let it flush automatically on the background thread
```

If the AgentEval server is unreachable, traces are queued to `.agenteval/pending_traces.jsonl` and retried on the next flush — **your agent never blocks or crashes because AgentEval is down.**

## Using the CLI

```bash
pip install -e "backend[cli]"   # from the repo root

agenteval scorers                                        # list built-in scorers
agenteval run --config agenteval.yaml --local --gate      # evaluate + apply gate policy, offline
agenteval run --config agenteval.yaml --local --report-file report.json
```

Exit codes: `0` = gate passed · `1` = gate failed (regression/threshold breach) · `2` = infrastructure/config error. CI systems should only treat `1` as "the agent regressed" — `2` means something is broken about the pipeline itself (bad config, unreachable dataset, etc.), not the agent.

## Using the REST API

Interactive docs at `/docs` (Swagger) once the API is running. Core flow:

```bash
# Create an API key (requires a dashboard session token from /v1/auth/login)
curl -X POST http://localhost:8000/v1/api-keys \
  -H "Authorization: Bearer <session_jwt>" \
  -H "Content-Type: application/json" \
  -d '{"project_id": "<uuid>", "name": "ci-key"}'

# Ingest a trace
curl -X POST http://localhost:8000/v1/traces \
  -H "Authorization: Bearer <api_key>" -H "Content-Type: application/json" \
  -d '{"environment": "production", "spans": [{"span_type": "llm_call", "name": "generate", "input": {"q": "hi"}, "output": {"a": "hello"}}]}'

# Trigger an eval run (precomputed_outputs required for direct API triggers --
# see "Regression testing & baselines" below for why)
curl -X POST http://localhost:8000/v1/eval-runs \
  -H "Authorization: Bearer <api_key>" -H "Content-Type: application/json" \
  -d '{"dataset_version_id": "<uuid>", "eval_suite_id": "<uuid>", "precomputed_outputs": {"<test_case_id>": "some output"}}'
```

Full endpoint reference: [`docs/SRS.md` section 7](docs/SRS.md#7-api-design). All 19 implemented endpoints are listed with request/response shapes.

## Using the dashboard

1. **Traces** — every ingested run, filterable by environment, with a span waterfall detail view (click any row).
2. **Datasets** — create datasets and inspect version history (each edit is a new immutable version).
3. **Eval Runs** — per-test-case results table, aggregate score cards, and a **baseline diff** view showing exactly which test cases regressed, with the statistical significance of each delta (not just raw numbers).
4. **Trends** — score and latency history across completed runs.

The dashboard authenticates with a **project API key** (not a full dashboard JWT session) for simplicity in this reference build — paste the key from `make seed`'s output on the login screen. JWT-based user/org login is implemented server-side (`/v1/auth/login`) for multi-user account management; wiring the dashboard's own login flow to it is a natural next extension (see [Known Limitations](#known-limitations--whats-not-included)).

## Creating datasets, scorers, and eval suites

**Dataset + version:**

```bash
curl -X POST http://localhost:8000/v1/datasets -H "Authorization: Bearer $KEY" \
  -d '{"project_id": "'$PROJECT_ID'", "name": "support-qa"}'

curl -X POST http://localhost:8000/v1/datasets/$DATASET_ID/versions -H "Authorization: Bearer $KEY" \
  -d '{"test_cases": [{"input": "how do I get a refund?", "expected_output": "...", "tags": ["critical"]}]}'
```

Or locally, from a JSONL file — `agenteval_core.Dataset.from_jsonl("data.jsonl")` (each line: `{"input": ..., "expected_output": ..., "tags": [...]}`).

**Scorer:**

```bash
curl -X POST http://localhost:8000/v1/scorers -H "Authorization: Bearer $KEY" \
  -d '{"project_id": "'$PROJECT_ID'", "name": "faithfulness_check", "scorer_type": "llm_judge",
       "config": {"rubric_template": "Score 0-1 how faithful the response is to the input. Input: {input} Output: {output}"}}'
```

Built-in `scorer_type` values: `exact_match`, `contains`, `regex_match`, `json_schema_valid`, `levenshtein_similarity`, `latency_threshold`, `cost_threshold`, `llm_judge`.

**Eval suite** (bundles scorer versions with weights and critical flags):

```bash
curl -X POST http://localhost:8000/v1/eval-suites -H "Authorization: Bearer $KEY" \
  -d '{"project_id": "'$PROJECT_ID'", "name": "core-suite", "scorer_version_ids": ["'$SCORER_VERSION_ID'"], "critical_scorer_version_ids": ["'$SCORER_VERSION_ID'"]}'
```

## Regression testing & baselines

1. Run an eval, then mark it as the baseline: `POST /v1/eval-runs/{id}/set-baseline`. Baselines are scoped per `(dataset, eval_suite)` pair and persist as the dataset evolves through new versions.
2. Run a new eval (e.g., after a prompt change).
3. `GET /v1/eval-runs/{id}/diff` compares the new run to the registered baseline (or an explicit `?baseline=<id>`), returning:
   - `aggregate_delta` — mean score change per scorer
   - `regressed_cases` / `improved_cases` — exact test cases that changed
   - `significance` — a paired bootstrap 95%-CI significance test per scorer, so a small noisy fluctuation in LLM-judge scores is never reported as a false regression (see [ADR-3](docs/architecture-decisions.md#adr-3-statistical-significance-testing-on-regressions-not-raw-deltas))

**Note on triggering runs via the raw API:** `POST /v1/eval-runs` requires `precomputed_outputs` — the API does not execute your agent for you (it doesn't have a way to reach arbitrary agent code running elsewhere). Compute your agent's outputs yourself and pass them in, or use the **CLI's local mode**, which does invoke your runner for you via `agenteval.yaml`.

## CI/CD integration

`agenteval.yaml`:

```yaml
project: my-agent
dataset: data/support-qa.jsonl
runner: "python ci/run_agent.py"     # reads test-case input as JSON on stdin, prints JSON output to stdout
scorers:
  - name: exact_match_check
    type: exact_match
    is_critical: true
gate:
  mode: block                        # block | warn
  min_mean_score:
    exact_match: 0.90
  max_regression_delta: 0.05
  critical_tags: ["critical"]
```

GitHub Actions, using the bundled composite action:

```yaml
- uses: actions/checkout@v4
- uses: ./.github/actions/agenteval-gate
  with:
    config: agenteval.yaml
  env:
    OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

See `.github/workflows/example-pr-gate.yml` for a full reference workflow, and this repo's own `.github/workflows/ci.yml` (`dogfood-example-agent` job) for a live example of AgentEval gating its own example agent in CI — a genuinely useful "does the tool work" smoke test, not just a demo.

## Example workflow, end to end

The fastest way to see the whole system work is `examples/example-support-agent/` — a small, fully working reference agent with its own dataset and config:

```bash
cd backend && pip install -e ".[cli]"
cd ..
PYTHONPATH=backend python -m agenteval_cli.main run \
  --config examples/example-support-agent/agenteval.yaml --local --gate
```

This has been run and verified against this exact repository — it produces a 100% pass rate and exits `0`. See `examples/example-support-agent/README.md` for the network-mode (real trace ingestion) variant.

## Running tests

```bash
# Unit tests -- pure logic, no external services, run these first
cd backend && PYTHONPATH=. pytest tests/unit -v

# Integration tests -- require Postgres + Redis + a running Celery worker
docker compose up -d postgres redis
alembic upgrade head
celery -A agenteval_worker.tasks:celery_app worker --loglevel=info &
PYTHONPATH=. DATABASE_URL=postgresql+asyncpg://agenteval:agenteval@localhost:5432/agenteval \
  REDIS_URL=redis://localhost:6379/0 pytest tests/integration -v
```

All 27 tests in this repository (21 unit + 6 integration, including a live end-to-end run through the real Celery pipeline and the single most important security regression test — cross-tenant trace isolation) pass against a real Postgres 16 + Redis 7 stack, not mocks.

Frontend: `cd frontend && npx tsc -b && npm run build` (type-checks and produces a real production bundle).

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `alembic upgrade head` hangs or errors | Postgres not reachable yet | `docker compose ps` — wait for `postgres` healthcheck to pass, or check `DATABASE_URL` |
| Eval run stuck in `pending` forever | No Celery worker running | Start one: `celery -A agenteval_worker.tasks:celery_app worker --loglevel=info` |
| `401 Invalid or revoked API key` | Wrong key, or key revoked | Re-run `make seed`, or create a new key via `POST /v1/api-keys` |
| `404 Not Found` on a trace/dataset you just created | Using the wrong project's API key | Every resource is scoped to the project that owns the API key — this is intentional (tenant isolation), not a bug |
| `llm_judge` scorer errors with `error: "..."` in results | Missing/invalid provider API key | Set `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` in `.env`, or switch `JUDGE_PROVIDER=ollama` for a fully offline path |
| Frontend shows a blank page | API not reachable from the browser | Check `CORS_ORIGINS` includes your frontend's origin, and that the API is actually running on the expected port |
| `MissingGreenlet` error in backend logs | A route accessed an unloaded SQLAlchemy relationship lazily under `AsyncSession` | Query explicitly with `select(...)` instead of touching a lazy relationship attribute — see the comment in `agenteval_api/routers/traces.py`'s `get_trace` for the pattern to follow |

## Deployment

- **Docker Compose** is the supported path for small/self-hosted deployments (single VM, small team).
- For production Kubernetes deployment, see [Known Limitations](#known-limitations--whats-not-included) — a Helm chart is specified in `docs/SRS.md` section 14.2 but not included in this repository yet.
- Whatever the deployment target: run migrations as a **one-shot job before** starting API replicas (the `migrate` Compose service demonstrates this pattern) — never run `alembic upgrade head` in a container's startup command with multiple replicas, which causes migration race conditions.
- Put a real secrets manager in front of `SECRET_KEY`, `OPENAI_API_KEY`, etc. in production — `.env` is for local development only.

## Known limitations & what's not included

This repository implements the core, real, end-to-end system (SRS phases 0–5: core engine, SDK, CLI, backend API, async evaluation orchestration, and a working dashboard). It deliberately does **not** include the following advanced-hardening pieces from the full specification (`docs/SRS.md`), to avoid shipping half-built, unsafe versions of them:

- **Sandboxed custom-code scorers** — `scorer_type: custom_python` is specified (SRS FR-SCORE-3) but not implemented, because running untrusted user code safely requires real container-per-execution isolation (see [ADR-4](docs/architecture-decisions.md#adr-4-custom-scorer-code-execution-is-sandboxed-or-disabled)). Only built-in and `llm_judge` scorers are available today.
- **Kubernetes / Helm chart** — Docker Compose is the only supported deployment path right now; a Helm chart with queue-depth-based worker autoscaling is designed (SRS section 14.2) but not built.
- **Production monitoring & alerting** (scheduled trace sampling, Slack/webhook alerts, human review queue) — designed (SRS section 3.7) but not implemented; the `AlertRule` table exists in the schema for future use.
- **OAuth/GitHub login** for the dashboard — email/password JWT auth is implemented; OAuth is a documented extension point, not built.
- **Load testing suite & Grafana dashboards** — the API exposes standard FastAPI instrumentation hooks, but the k6 scripts and committed Grafana JSON described in the SRS aren't included.
- **Frontend API types** are hand-maintained (`frontend/src/api/client.ts`) rather than generated from the OpenAPI spec — fine at this scale, but should be automated (`openapi-typescript`) before the API surface grows much further.

If you're evaluating this as a portfolio piece: the interesting engineering is in what **is** here — the dual-mode evaluation engine, the real async Celery pipeline (fan-out/fan-in with a chord, verified against a live worker), the statistical regression detection, and the tenant-isolation security testing — not in checking every box from the original spec.

## Project structure

```
agenteval/
├── backend/
│   ├── agenteval_core/     # framework-agnostic evaluation engine (scorers, engine, stats)
│   ├── agenteval_api/      # FastAPI app: routers, ORM models, schemas, auth, celery_app
│   ├── agenteval_worker/   # Celery tasks (score_test_case, finalize_run)
│   ├── agenteval_sdk/      # pip-installable client SDK (trace/span, local + network Client)
│   ├── agenteval_cli/      # `agenteval` CLI (run, gate policy, config parsing)
│   ├── migrations/         # Alembic, generated + verified against real Postgres
│   ├── tests/unit/         # 21 tests, zero external services
│   ├── tests/integration/  # 6 tests, real Postgres + Redis + Celery worker
│   └── Dockerfile, Dockerfile.worker
├── frontend/                # React + TS + Vite + Tailwind dashboard
├── examples/example-support-agent/  # working reference agent used throughout this README
├── .github/workflows/, .github/actions/agenteval-gate/
├── docs/SRS.md, docs/implementation-roadmap.md, docs/architecture-decisions.md
├── docker-compose.yml
└── Makefile
```

## License

MIT — see [LICENSE](LICENSE).
