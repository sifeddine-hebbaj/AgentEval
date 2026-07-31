# Contributing to AgentEval

Thanks for considering a contribution.

## Development setup

```bash
git clone <this-repo>
cd agenteval
cp .env.example .env
docker compose up --build -d
make seed
```

See the main [README](README.md) for the full local development workflow,
including running tests without Docker.

## Before opening a PR

- `make lint` passes (ruff + mypy on the backend, eslint + tsc on the frontend)
- `make test` passes (unit tests always; integration tests if you have
  Postgres/Redis available)
- New endpoints have integration test coverage, especially around
  tenant isolation (`project_id` scoping) -- see
  `backend/tests/integration/test_api_traces_and_datasets.py` for the
  pattern.
- New scorers never raise -- they must catch their own exceptions and
  return `ScoreResult(error=...)` (see `agenteval_core/scorers/base.py`).

## Project structure & architecture

Read `docs/SRS.md` (the original Software Requirements Specification)
and `docs/architecture-decisions.md` before making structural changes,
especially before touching `agenteval_core` -- its zero-framework-
dependency constraint (SRS section 5.6) is deliberate and load-bearing;
see that section before adding any FastAPI/SQLAlchemy import there.

## Reporting security issues

Please do not open a public issue for security vulnerabilities. Instead
open a private security advisory on GitHub, or email the maintainers
directly (see repository settings for contact info).
