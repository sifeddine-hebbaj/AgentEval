"""Scorer registry & Eval Suites (SRS section 3.4).

Scorers are versioned: editing a rubric/config creates a new
ScorerVersion rather than mutating the old one, so historical Eval
Results always resolve to the exact config they were scored against
(FR-SCORE-5).
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agenteval_api.db import get_db
from agenteval_api.deps import get_current_project_id
from agenteval_api.models.orm import EvalSuite, EvalSuiteScorer, Scorer, ScorerVersion
from agenteval_api.schemas.schemas import (
    EvalSuiteCreateRequest,
    EvalSuiteResponse,
    ScorerCreateRequest,
    ScorerVersionResponse,
)
from agenteval_core.scorers import registry as core_registry

router = APIRouter(prefix="/v1/scorers", tags=["scorers"])
suites_router = APIRouter(prefix="/v1/eval-suites", tags=["eval-suites"])


@router.post("", response_model=ScorerVersionResponse, status_code=status.HTTP_201_CREATED)
async def create_scorer(
    payload: ScorerCreateRequest,
    db: AsyncSession = Depends(get_db),
    project_id: UUID = Depends(get_current_project_id),
):
    if payload.scorer_type not in core_registry.names() and payload.scorer_type != "llm_judge":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown scorer_type '{payload.scorer_type}'. Available: {core_registry.names()}",
        )

    result = await db.execute(
        select(Scorer).where(Scorer.project_id == project_id, Scorer.name == payload.name)
    )
    scorer = result.scalar_one_or_none()
    if scorer is None:
        scorer = Scorer(project_id=project_id, name=payload.name, scorer_type=payload.scorer_type)
        db.add(scorer)
        await db.flush()

    version_count_result = await db.execute(
        select(func.max(ScorerVersion.version_number)).where(ScorerVersion.scorer_id == scorer.id)
    )
    next_version = (version_count_result.scalar() or 0) + 1

    version = ScorerVersion(
        scorer_id=scorer.id,
        version_number=next_version,
        config=payload.config,
        output_type=payload.output_type,
    )
    db.add(version)
    await db.commit()
    await db.refresh(version)
    
    # Return response with synthetic fields
    return ScorerVersionResponse(
        id=version.id,
        scorer_id=version.scorer_id,
        scorer_name=scorer.name,
        scorer_type=scorer.scorer_type,
        project_id=project_id,
        version_number=version.version_number,
        config=version.config,
        output_type=version.output_type,
        created_at=version.created_at,
    )


@router.get("", response_model=list[ScorerVersionResponse])
async def list_scorers(
    db: AsyncSession = Depends(get_db),
    project_id: UUID = Depends(get_current_project_id),
):
    result = await db.execute(
        select(Scorer).where(Scorer.project_id == project_id)
    )
    scorers = result.scalars().all()
    
    # Get latest versions for each scorer
    responses = []
    for scorer in scorers:
        version_result = await db.execute(
            select(ScorerVersion).where(ScorerVersion.scorer_id == scorer.id).order_by(ScorerVersion.version_number.desc()).limit(1)
        )
        version = version_result.scalar_one_or_none()
        if version:
            responses.append(ScorerVersionResponse(
                id=version.id,
                scorer_id=version.scorer_id,
                scorer_name=scorer.name,
                scorer_type=scorer.scorer_type,
                project_id=project_id,
                version_number=version.version_number,
                config=version.config,
                output_type=version.output_type,
                created_at=version.created_at,
            ))
    
    return responses


@router.get("/{scorer_id}/versions", response_model=list[ScorerVersionResponse])
async def list_scorer_versions(
    scorer_id: UUID,
    db: AsyncSession = Depends(get_db),
    project_id: UUID = Depends(get_current_project_id),
):
    result = await db.execute(
        select(Scorer).where(Scorer.id == scorer_id, Scorer.project_id == project_id)
    )
    scorer = result.scalar_one_or_none()
    if scorer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scorer not found")
    
    result = await db.execute(
        select(ScorerVersion).where(ScorerVersion.scorer_id == scorer_id)
    )
    return result.scalars().all()


@router.post("/{scorer_id}/versions", response_model=ScorerVersionResponse, status_code=status.HTTP_201_CREATED)
async def create_scorer_version(
    scorer_id: UUID,
    db: AsyncSession = Depends(get_db),
    project_id: UUID = Depends(get_current_project_id),
):
    result = await db.execute(
        select(Scorer).where(Scorer.id == scorer_id, Scorer.project_id == project_id)
    )
    scorer = result.scalar_one_or_none()
    if scorer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scorer not found")
    
    version_count_result = await db.execute(
        select(func.max(ScorerVersion.version_number)).where(ScorerVersion.scorer_id == scorer_id)
    )
    next_version = (version_count_result.scalar() or 0) + 1
    
    version = ScorerVersion(
        scorer_id=scorer.id,
        version_number=next_version,
        config={},
        output_type="numeric",
    )
    db.add(version)
    await db.commit()
    await db.refresh(version)
    
    # Add synthetic fields for response
    response = ScorerVersionResponse(
        id=version.id,
        scorer_id=version.scorer_id,
        scorer_name=scorer.name,
        scorer_type=scorer.scorer_type,
        project_id=project_id,
        version_number=version.version_number,
        config=version.config,
        output_type=version.output_type,
        created_at=version.created_at,
    )
    return response


@suites_router.get("", response_model=list[EvalSuiteResponse])
async def list_eval_suites(
    db: AsyncSession = Depends(get_db),
    project_id: UUID = Depends(get_current_project_id),
):
    result = await db.execute(
        select(EvalSuite).where(EvalSuite.project_id == project_id)
    )
    suites = result.scalars().all()
    
    # Enrich with scorer_version_ids for each suite
    enriched_suites = []
    for suite in suites:
        scorer_result = await db.execute(
            select(EvalSuiteScorer).where(EvalSuiteScorer.eval_suite_id == suite.id)
        )
        scorer_links = scorer_result.scalars().all()
        scorer_version_ids = [link.scorer_version_id for link in scorer_links]
        
        # Create a dict representation with the additional field
        suite_dict = {
            "id": suite.id,
            "project_id": suite.project_id,
            "name": suite.name,
            "scorer_version_ids": scorer_version_ids
        }
        enriched_suites.append(suite_dict)
    
    return enriched_suites


@suites_router.post("", response_model=EvalSuiteResponse, status_code=status.HTTP_201_CREATED)
async def create_eval_suite(
    payload: EvalSuiteCreateRequest,
    db: AsyncSession = Depends(get_db),
    project_id: UUID = Depends(get_current_project_id),
):
    suite = EvalSuite(project_id=project_id, name=payload.name)
    db.add(suite)
    await db.flush()

    for sv_id in payload.scorer_version_ids:
        db.add(
            EvalSuiteScorer(
                eval_suite_id=suite.id,
                scorer_version_id=sv_id,
                weight=payload.weights.get(str(sv_id), 1.0),
                is_critical=sv_id in payload.critical_scorer_version_ids,
            )
        )
    await db.commit()
    await db.refresh(suite)
    
    # Enrich response with scorer_version_ids
    scorer_result = await db.execute(
        select(EvalSuiteScorer).where(EvalSuiteScorer.eval_suite_id == suite.id)
    )
    scorer_links = scorer_result.scalars().all()
    scorer_version_ids = [link.scorer_version_id for link in scorer_links]
    
    # Return dict with scorer_version_ids
    return {
        "id": suite.id,
        "project_id": suite.project_id,
        "name": suite.name,
        "scorer_version_ids": scorer_version_ids
    }
