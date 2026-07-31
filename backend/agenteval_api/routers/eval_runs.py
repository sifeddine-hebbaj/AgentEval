"""Eval Run orchestration: trigger, status, results, baseline diff
(SRS section 3.5, FR-EVAL-*).
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agenteval_api.db import get_db
from agenteval_api.deps import get_current_project_id
from agenteval_api.models.orm import (
    Baseline,
    DatasetVersion,
    EvalResult as EvalResultORM,
    EvalRun,
    Score,
    TestCaseORM,
)
from agenteval_api.schemas.schemas import (
    EvalResultOut,
    EvalRunCreateRequest,
    EvalRunDiffResponse,
    EvalRunResponse,
    RegressedCase,
    ScoreOut,
    SignificanceEntry,
)
from agenteval_core.stats import bootstrap_paired_delta
from agenteval_core.stats import SignificanceResult as StatsSignificanceResult

router = APIRouter(prefix="/v1/eval-runs", tags=["eval-runs"])


@router.post("", response_model=EvalRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_eval_run(
    payload: EvalRunCreateRequest,
    db: AsyncSession = Depends(get_db),
    project_id: UUID = Depends(get_current_project_id),
):
    version = await db.get(DatasetVersion, payload.dataset_version_id)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset version not found.")

    result = await db.execute(select(TestCaseORM).where(TestCaseORM.dataset_version_id == version.id))
    test_cases = result.scalars().all()
    if not test_cases:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Dataset version has no test cases.")

    if payload.precomputed_outputs is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "precomputed_outputs is required when triggering a run via the API directly. "
                "Run the agent-under-test yourself and supply {test_case_id: output} pairs, "
                "or use the CLI's local mode which invokes the runner for you."
            ),
        )

    run = EvalRun(
        project_id=project_id,
        dataset_version_id=payload.dataset_version_id,
        eval_suite_id=payload.eval_suite_id,
        baseline_run_id=payload.baseline_run_id,
        status="pending",
        trigger_source=payload.trigger_source,
        git_sha=payload.git_sha,
        total_test_cases=len(test_cases),
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    from agenteval_worker.tasks import dispatch_eval_run

    dispatch_eval_run(
        run_id=str(run.id),
        project_id=str(project_id),
        eval_suite_id=str(payload.eval_suite_id),
        dataset_version_id=str(payload.dataset_version_id),
        test_case_ids=[str(tc.id) for tc in test_cases],
        precomputed_outputs=payload.precomputed_outputs,
    )

    return run


async def _get_owned_run(run_id: UUID, db: AsyncSession, project_id: UUID) -> EvalRun:
    run = await db.get(EvalRun, run_id)
    if run is None or run.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Eval run not found.")
    return run


@router.get("", response_model=list[EvalRunResponse])
async def list_eval_runs(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    project_id: UUID = Depends(get_current_project_id),
):
    result = await db.execute(
        select(EvalRun).where(EvalRun.project_id == project_id).order_by(EvalRun.started_at.desc()).limit(limit)
    )
    return result.scalars().all()


@router.get("/{run_id}", response_model=EvalRunResponse)
async def get_eval_run(
    run_id: UUID, db: AsyncSession = Depends(get_db), project_id: UUID = Depends(get_current_project_id)
):
    return await _get_owned_run(run_id, db, project_id)


@router.get("/{run_id}/results", response_model=list[EvalResultOut])
async def get_eval_run_results(
    run_id: UUID, db: AsyncSession = Depends(get_db), project_id: UUID = Depends(get_current_project_id)
):
    await _get_owned_run(run_id, db, project_id)
    result = await db.execute(select(EvalResultORM).where(EvalResultORM.eval_run_id == run_id))
    rows = result.scalars().all()
    out = []
    for row in rows:
        scores_result = await db.execute(select(Score).where(Score.eval_result_id == row.id))
        scores = scores_result.scalars().all()
        out.append(
            EvalResultOut(
                id=row.id,
                test_case_id=row.test_case_id,
                actual_output=row.actual_output,
                status=row.status,
                latency_ms=row.latency_ms,
                scores=[
                    ScoreOut(
                        scorer_name=s.scorer_name,
                        numeric_value=s.numeric_value,
                        boolean_value=s.boolean_value,
                        category_value=s.category_value,
                        rationale=s.rationale,
                        error=s.error,
                    )
                    for s in scores
                ],
            )
        )
    return out


@router.post("/{run_id}/set-baseline", status_code=status.HTTP_204_NO_CONTENT)
async def set_baseline(
    run_id: UUID, db: AsyncSession = Depends(get_db), project_id: UUID = Depends(get_current_project_id)
):
    run = await _get_owned_run(run_id, db, project_id)
    version = await db.get(DatasetVersion, run.dataset_version_id)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset version not found.")

    result = await db.execute(
        select(Baseline).where(
            Baseline.project_id == project_id,
            Baseline.dataset_id == version.dataset_id,
            Baseline.eval_suite_id == run.eval_suite_id,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.eval_run_id = run_id
    else:
        db.add(
            Baseline(
                project_id=project_id, dataset_id=version.dataset_id, eval_suite_id=run.eval_suite_id, eval_run_id=run_id
            )
        )
    await db.commit()


@router.get("/{run_id}/diff", response_model=EvalRunDiffResponse)
async def get_diff(
    run_id: UUID,
    baseline: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    project_id: UUID = Depends(get_current_project_id),
):
    run = await _get_owned_run(run_id, db, project_id)

    baseline_run_id = baseline or run.baseline_run_id
    if baseline_run_id is None:
        version = await db.get(DatasetVersion, run.dataset_version_id)
        if version is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset version not found.")
        result = await db.execute(
            select(Baseline).where(
                Baseline.project_id == project_id,
                Baseline.dataset_id == version.dataset_id,
                Baseline.eval_suite_id == run.eval_suite_id,
            )
        )
        baseline_row = result.scalar_one_or_none()
        if baseline_row is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No baseline specified and no baseline is registered for this dataset+suite.",
            )
        baseline_run_id = baseline_row.eval_run_id

    await _get_owned_run(baseline_run_id, db, project_id)

    new_results = (await db.execute(select(EvalResultORM).where(EvalResultORM.eval_run_id == run_id))).scalars().all()
    baseline_results = (
        (await db.execute(select(EvalResultORM).where(EvalResultORM.eval_run_id == baseline_run_id))).scalars().all()
    )
    baseline_result_by_tc = {r.test_case_id: r for r in baseline_results}

    per_scorer_pairs: dict[str, list[tuple[float, float]]] = {}
    regressed: list[RegressedCase] = []
    improved: list[RegressedCase] = []

    for new_row in new_results:
        baseline_row = baseline_result_by_tc.get(new_row.test_case_id)
        if baseline_row is None:
            continue
        new_scores = {s.scorer_name: s for s in (await db.execute(select(Score).where(Score.eval_result_id == new_row.id))).scalars().all()}
        base_scores = {s.scorer_name: s for s in (await db.execute(select(Score).where(Score.eval_result_id == baseline_row.id))).scalars().all()}

        for scorer_name, new_score in new_scores.items():
            base_score = base_scores.get(scorer_name)
            if base_score is None:
                continue
            nv = new_score.numeric_value if new_score.numeric_value is not None else (1.0 if new_score.boolean_value else 0.0)
            bv = base_score.numeric_value if base_score.numeric_value is not None else (1.0 if base_score.boolean_value else 0.0)
            per_scorer_pairs.setdefault(scorer_name, []).append((bv, nv))

            delta = nv - bv
            if delta < -0.05:
                regressed.append(
                    RegressedCase(
                        test_case_id=str(new_row.test_case_id),
                        scorer=scorer_name,
                        baseline_score=bv,
                        new_score=nv,
                    )
                )
            elif delta > 0.05:
                improved.append(
                    RegressedCase(
                        test_case_id=str(new_row.test_case_id),
                        scorer=scorer_name,
                        baseline_score=bv,
                        new_score=nv,
                    )
                )

    significance = {}
    for scorer_name, pairs in per_scorer_pairs.items():
        if len(pairs) < 2:
            continue
        baseline_vals = [p[0] for p in pairs]
        new_vals = [p[1] for p in pairs]
        result = bootstrap_paired_delta(baseline_vals, new_vals, iterations=1000)
        significance[scorer_name] = SignificanceEntry(
            mean_delta=result.mean_delta,
            ci_low=result.ci_low,
            ci_high=result.ci_high,
            significant=result.significant,
            p_value_approx=result.p_value_approx,
        )

    aggregate_delta = {}
    for scorer_name, pairs in per_scorer_pairs.items():
        baseline_vals = [p[0] for p in pairs]
        new_vals = [p[1] for p in pairs]
        aggregate_delta[scorer_name] = sum(n - b for b, n in zip(baseline_vals, new_vals)) / len(pairs)

    return EvalRunDiffResponse(
        run_id=run_id,
        baseline_id=baseline_run_id,
        aggregate_delta=aggregate_delta,
        regressed_cases=regressed,
        improved_cases=improved,
        significance=significance,
    )
