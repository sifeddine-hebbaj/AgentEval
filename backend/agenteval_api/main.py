"""FastAPI application factory."""
from __future__ import annotations

import time

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from agenteval_api.config import settings
from agenteval_api.routers import auth, datasets, eval_runs, metrics, projects, scorers, traces

limiter = Limiter(key_func=get_remote_address, default_limits=[f"{settings.rate_limit_per_minute}/minute"])


def create_app() -> FastAPI:
    app = FastAPI(
        title="AgentEval API",
        description="Open-source agent evaluation & regression testing framework.",
        version="0.1.0",
    )

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def add_request_id_and_timing(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Process-Time-Ms"] = str(int((time.perf_counter() - start) * 1000))
        return response

    @app.exception_handler(Exception)
    async def problem_details_handler(request: Request, exc: Exception):
        # RFC 7807 Problem Details for unhandled exceptions (SRS section 7.1).
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "type": "about:blank",
                "title": "Internal Server Error",
                "status": 500,
                "detail": "An unexpected error occurred. This has been logged.",
                "instance": str(request.url),
            },
        )

    app.include_router(auth.router)
    app.include_router(auth.keys_router)
    app.include_router(projects.router)
    app.include_router(projects.org_router)
    app.include_router(traces.router)
    app.include_router(datasets.router)
    app.include_router(scorers.router)
    app.include_router(scorers.suites_router)
    app.include_router(eval_runs.router)
    app.include_router(metrics.router)

    @app.get("/healthz", tags=["health"])
    async def healthz():
        return {"status": "ok"}

    return app


app = create_app()
