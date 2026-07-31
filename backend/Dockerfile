FROM python:3.11-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY agenteval_core ./agenteval_core
COPY agenteval_api ./agenteval_api
COPY agenteval_worker ./agenteval_worker
COPY agenteval_sdk ./agenteval_sdk
COPY agenteval_cli ./agenteval_cli
COPY migrations ./migrations
COPY alembic.ini ./

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir ".[api,judge-openai,judge-anthropic,judge-local,sdk,cli]"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

CMD ["uvicorn", "agenteval_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
