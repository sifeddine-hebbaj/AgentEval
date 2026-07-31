"""Trace ingestion & retrieval (SRS section 3.3, FR-TRACE-*).

Ingestion returns 202 Accepted and never blocks on downstream processing
(NFR-AVAIL-2's server-side counterpart: the SDK's non-blocking flush
only helps if the API itself responds fast).
"""
from __future__ import annotations

import json
from datetime import UTC
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agenteval_api.config import settings
from agenteval_api.db import get_db
from agenteval_api.deps import get_current_project_id
from agenteval_api.models.orm import Span, Trace
from agenteval_api.schemas.schemas import TraceDetailOut, TraceIn, TraceOut

router = APIRouter(prefix="/v1/traces", tags=["traces"])


def _offload_if_large(payload) -> dict:
    """Inline if small, reference-shaped stub if large (SRS section 6.3).

    A real deployment would upload to MinIO/S3 here; kept as a documented
    extension point (object_storage.py) rather than requiring MinIO for
    every local dev setup.
    """
    serialized = json.dumps(payload, default=str)
    if len(serialized.encode("utf-8")) > settings.max_inline_payload_bytes:
        from agenteval_api.object_storage import upload_large_payload

        key = upload_large_payload(serialized)
        return {"storage": "s3", "key": key}
    return {"inline": payload}


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def ingest_trace(
    payload: TraceIn,
    db: AsyncSession = Depends(get_db),
    project_id: UUID = Depends(get_current_project_id),
):
    trace = Trace(
        id=payload.id,
        project_id=project_id,
        environment=payload.environment,
        metadata_=payload.metadata,
        status=payload.status,
        started_at=payload.started_at,
        ended_at=payload.ended_at,
    )
    if trace.started_at is None:
        from datetime import datetime

        trace.started_at = datetime.now(UTC)

    total_tokens, total_cost = 0, 0.0
    for span_in in payload.spans:
        span = Span(
            id=span_in.id,
            trace_id=trace.id,
            parent_span_id=span_in.parent_span_id,
            span_type=span_in.span_type,
            name=span_in.name,
            input_ref=_offload_if_large(span_in.input),
            output_ref=_offload_if_large(span_in.output),
            model_name=span_in.model_name,
            prompt_tokens=span_in.prompt_tokens,
            completion_tokens=span_in.completion_tokens,
            cost=span_in.cost,
            status=span_in.status,
            error_message=span_in.error_message,
            started_at=span_in.started_at,
            ended_at=span_in.ended_at,
        )
        total_tokens += span_in.prompt_tokens + span_in.completion_tokens
        total_cost += span_in.cost
        trace.spans.append(span)

    trace.total_tokens = total_tokens
    trace.total_cost = total_cost
    if trace.ended_at and trace.started_at:
        trace.duration_ms = int((trace.ended_at - trace.started_at).total_seconds() * 1000)

    db.add(trace)
    await db.commit()
    return {"id": trace.id, "status": "accepted"}


@router.post("/batch", status_code=status.HTTP_202_ACCEPTED)
async def ingest_traces_batch(
    payloads: list[TraceIn],
    db: AsyncSession = Depends(get_db),
    project_id: UUID = Depends(get_current_project_id),
):
    accepted = []
    for payload in payloads:
        result = await ingest_trace(payload, db, project_id)
        accepted.append(result["id"])
    return {"accepted": accepted}


@router.get("", response_model=list[TraceOut])
async def list_traces(
    environment: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    db: AsyncSession = Depends(get_db),
    project_id: UUID = Depends(get_current_project_id),
):
    stmt = select(Trace).where(Trace.project_id == project_id).order_by(Trace.started_at.desc()).limit(limit)
    if environment:
        stmt = stmt.where(Trace.environment == environment)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{trace_id}", response_model=TraceDetailOut)
async def get_trace(
    trace_id: UUID,
    db: AsyncSession = Depends(get_db),
    project_id: UUID = Depends(get_current_project_id),
):
    trace = await db.get(Trace, trace_id)
    # Enforce tenant isolation even on a direct-by-id lookup (SRS 12.2):
    # never trust that trace_id alone is enough, always re-check project_id.
    if trace is None or trace.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trace not found.")

    # Explicit query rather than the lazy `trace.spans` relationship:
    # under AsyncSession, touching an unloaded relationship attribute
    # outside of an active await triggers a MissingGreenlet error, since
    # lazy-loading needs to run through the async driver. Fetching all
    # spans for the trace in one query also avoids an N+1 pattern.
    spans_result = await db.execute(select(Span).where(Span.trace_id == trace_id))
    spans = spans_result.scalars().all()

    return TraceDetailOut(
        id=trace.id,
        environment=trace.environment,
        status=trace.status,
        total_tokens=trace.total_tokens,
        total_cost=trace.total_cost,
        duration_ms=trace.duration_ms,
        started_at=trace.started_at,
        ended_at=trace.ended_at,
        metadata=trace.metadata_,
        spans=[
            {
                "id": s.id,
                "parent_span_id": s.parent_span_id,
                "span_type": s.span_type,
                "name": s.name,
                "input": s.input_ref,
                "output": s.output_ref,
                "model_name": s.model_name,
                "prompt_tokens": s.prompt_tokens,
                "completion_tokens": s.completion_tokens,
                "cost": s.cost,
                "status": s.status,
                "error_message": s.error_message,
                "started_at": s.started_at,
                "ended_at": s.ended_at,
            }
            for s in spans
        ],
    )
