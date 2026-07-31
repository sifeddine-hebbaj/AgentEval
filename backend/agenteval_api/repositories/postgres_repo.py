"""Postgres-backed implementation of agenteval_core.EvalResultRepository.

This is the payoff of the dual-mode architecture (SRS section 5.6): the
Celery worker (agenteval_worker/tasks.py) wires EvalEngine to THIS
repository, while the CLI/SDK wire the exact same EvalEngine to
SQLiteEvalResultRepository. No orchestration logic is duplicated.

Note: this repository uses a synchronous psycopg2/SQLAlchemy session
(not the async engine used by the FastAPI app) because Celery workers
run in synchronous worker processes -- mixing asyncio event loops with
Celery's prefork/thread pool is a well-known source of subtle bugs, so
the worker deliberately uses sync SQLAlchemy against the same database.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from agenteval_core.models import EvalResult, EvalRunSummary, RunStatus, ScoreResult
from agenteval_api.models.orm import EvalRun, EvalResult as EvalResultORM, Score


def _sync_url(async_url: str) -> str:
    return async_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")


class PostgresEvalResultRepository:
    def __init__(self, database_url: str, project_id: uuid.UUID, dataset_version_id: uuid.UUID, eval_suite_id: uuid.UUID):
        self.engine = create_engine(_sync_url(database_url), pool_pre_ping=True)
        self.Session: sessionmaker[Session] = sessionmaker(bind=self.engine)
        self.project_id = project_id
        self.dataset_version_id = dataset_version_id
        self.eval_suite_id = eval_suite_id

    def create_run(self, dataset_id: str, total_test_cases: int) -> EvalRunSummary:
        with self.Session() as session:
            run = EvalRun(
                project_id=self.project_id,
                dataset_version_id=self.dataset_version_id,
                eval_suite_id=self.eval_suite_id,
                status=RunStatus.PENDING.value,
                total_test_cases=total_test_cases,
                completed_test_cases=0,
            )
            session.add(run)
            session.commit()
            session.refresh(run)
            return EvalRunSummary(
                id=str(run.id),
                dataset_id=dataset_id,
                status=RunStatus(run.status),
                total_test_cases=run.total_test_cases,
                started_at=run.started_at,
            )

    def save_result(self, result: EvalResult) -> None:
        with self.Session() as session:
            row = EvalResultORM(
                eval_run_id=uuid.UUID(result.run_id),
                test_case_id=uuid.UUID(result.test_case_id),
                actual_output=result.actual_output,
                status=result.status,
                error_message=result.error_message,
                latency_ms=result.latency_ms,
            )
            session.add(row)
            session.flush()  # populate row.id before adding child Scores

            for scorer_name, score in result.scores.items():
                session.add(
                    Score(
                        eval_result_id=row.id,
                        scorer_name=scorer_name,
                        numeric_value=score.numeric_value,
                        boolean_value=score.boolean_value,
                        category_value=score.category_value,
                        rationale=score.rationale,
                        error=score.error,
                    )
                )

            run = session.get(EvalRun, uuid.UUID(result.run_id))
            run.completed_test_cases += 1
            session.commit()

    def get_run(self, run_id: str) -> EvalRunSummary:
        with self.Session() as session:
            run = session.get(EvalRun, uuid.UUID(run_id))
            if run is None:
                raise KeyError(f"eval run {run_id} not found")
            return EvalRunSummary(
                id=str(run.id),
                dataset_id=str(run.dataset_version_id),
                status=RunStatus(run.status),
                total_test_cases=run.total_test_cases,
                completed_test_cases=run.completed_test_cases,
                aggregate_metrics=run.aggregate_metrics or {},
                started_at=run.started_at,
                completed_at=run.completed_at,
            )

    def update_run_status(self, run_id: str, status: RunStatus, aggregate_metrics: dict | None = None) -> None:
        with self.Session() as session:
            run = session.get(EvalRun, uuid.UUID(run_id))
            run.status = status.value
            if aggregate_metrics is not None:
                run.aggregate_metrics = aggregate_metrics
            if status in (RunStatus.COMPLETED, RunStatus.PARTIAL, RunStatus.FAILED):
                run.completed_at = datetime.now(timezone.utc)
            session.commit()

    def get_run_results(self, run_id: str) -> list[EvalResult]:
        with self.Session() as session:
            rows = session.query(EvalResultORM).filter(EvalResultORM.eval_run_id == uuid.UUID(run_id)).all()
            results = []
            for row in rows:
                scores = {
                    s.scorer_name: ScoreResult(
                        numeric_value=s.numeric_value,
                        boolean_value=s.boolean_value,
                        category_value=s.category_value,
                        rationale=s.rationale,
                        error=s.error,
                    )
                    for s in row.scores
                }
                results.append(
                    EvalResult(
                        id=str(row.id),
                        run_id=str(row.eval_run_id),
                        test_case_id=str(row.test_case_id),
                        actual_output=row.actual_output,
                        status=row.status,
                        error_message=row.error_message,
                        latency_ms=row.latency_ms,
                        scores=scores,
                        created_at=row.created_at,
                    )
                )
            return results
