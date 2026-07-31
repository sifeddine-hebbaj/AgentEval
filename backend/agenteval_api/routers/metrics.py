"""Trend metrics for dashboard charts (SRS FR-UI-4, GET /v1/metrics/trends)."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agenteval_api.db import get_db
from agenteval_api.deps import get_current_project_id
from agenteval_api.models.orm import EvalRun

router = APIRouter(prefix="/v1/metrics", tags=["metrics"])


@router.get("/trends")
async def get_trends(
    limit: int = Query(default=50, le=500),
    db: AsyncSession = Depends(get_db),
    project_id: UUID = Depends(get_current_project_id),
):
    result = await db.execute(
        select(EvalRun)
        .where(EvalRun.project_id == project_id, EvalRun.status.in_(["completed", "partial"]))
        .order_by(EvalRun.completed_at.desc())
        .limit(limit)
    )
    runs = list(reversed(result.scalars().all()))
    return [
        {
            "run_id": str(r.id),
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "mean_scores": r.aggregate_metrics.get("mean_scores", {}),
            "pass_rate": r.aggregate_metrics.get("pass_rate"),
            "p50_latency_ms": r.aggregate_metrics.get("p50_latency_ms"),
            "p95_latency_ms": r.aggregate_metrics.get("p95_latency_ms"),
        }
        for r in runs
    ]
